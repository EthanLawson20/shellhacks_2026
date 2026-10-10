import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import GroupShuffleSplit
from sklearn.preprocessing import LabelEncoder, StandardScaler

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

MOTION_CROSS_THRESHOLD = 0.2
TEST_SIZE = 0.25
RANDOM_STATE = 0
PROVISIONAL_MIN_WINDOWS = 50
SUSPICIOUS_ACCURACY = 0.95
MAX_EPOCHS = 200
PATIENCE = 15
DEFAULT_DATASET = Path(__file__).resolve().parent.parent / "data" / "dataset.json"

# Order matters: it lines up with the feature vector built in _features().
FEATURE_NAMES = [
    "motion_mean", "motion_std", "motion_min", "motion_max", "motion_range",
    "motion_mad", "motion_crossings_0.2",
    "audio_mean", "audio_std", "audio_min", "audio_max", "audio_range", "audio_mad",
    "presence_frac", "rssi_mean",
]

tf.random.set_seed(RANDOM_STATE)


def _six_stats(x: np.ndarray) -> list:
    # mean, std, min, max, range, mean-abs-diff between consecutive samples.
    if x.size == 0:
        return [0.0] * 6
    mad = float(np.mean(np.abs(np.diff(x)))) if x.size > 1 else 0.0
    return [float(x.mean()), float(x.std()), float(x.min()), float(x.max()),
            float(x.max() - x.min()), mad]


def _up_crossings(x: np.ndarray, threshold: float) -> int:
    # Number of times the series rises through the threshold
    if x.size < 2:
        return 0
    return int(np.count_nonzero((x[:-1] <= threshold) & (x[1:] > threshold)))


def _features(readings: list) -> list:
    # Turn one windows names into fixed feature vector
    motion = np.array([float(r["motion"]) for r in readings], dtype=float)
    audio = np.array([float(r["audio_db"]) for r in readings
                      if r.get("audio_db") is not None], dtype=float)
    rssi = [float(r["rssi"]) for r in readings if r.get("rssi") is not None]
    presence = [1.0 if r.get("presence") else 0.0 for r in readings]

    feats = _six_stats(motion)
    feats.append(float(_up_crossings(motion, MOTION_CROSS_THRESHOLD)))
    feats += _six_stats(audio)
    feats.append(float(np.mean(presence)) if presence else 0.0)
    feats.append(float(np.mean(rssi)) if rssi else 0.0)
    return feats


def _print_confusion(cm: np.ndarray, labels: list) -> None:
    width = max(12, max(len(str(x)) for x in labels) + 2)
    cell = lambda v: f"{str(v)[:width - 1]:>{width}}"
    print("Confusion matrix (rows = true, columns = predicted):")
    print(cell("") + "".join(cell(x) for x in labels))
    for i, label in enumerate(labels):
        print(cell(label) + "".join(cell(int(cm[i, j])) for j in range(len(labels))))


def _new_model(n_features: int, n_classes: int) -> keras.Model:
    # Small multiclass network to detect changes in wifi feedback
    model = keras.Sequential([
        keras.Input(shape=(n_features,)),
        layers.Dense(64, activation="relu"),
        layers.Dropout(0.4),
        layers.Dense(32, activation="relu"),
        layers.Dropout(0.3),
        layers.Dense(n_classes, activation="softmax"),
    ])
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=1e-3),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model

# Train simple multiclass model
def _fit(model: keras.Model, X_train, y_train, X_val=None, y_val=None) -> None:
    callbacks = []
    validation_data = None
    if X_val is not None and len(X_val) > 0:
        validation_data = (X_val, y_val)
        callbacks.append(keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=PATIENCE, restore_best_weights=True))
    model.fit(
        X_train, y_train,
        validation_data=validation_data,
        epochs=MAX_EPOCHS,
        batch_size=32,
        callbacks=callbacks,
        verbose=0,
    )
    


def _print_importances(model: keras.Model, scaler: StandardScaler, X_ref: np.ndarray) -> None:
    """Neural nets have no built-in feature_importances_. Approximate it with a
    permutation importance against training-set accuracy loss (cruder than the
    RF's version, but gives the same kind of sanity-check signal)."""
    base_pred = np.argmax(model.predict(X_ref, verbose=0), axis=1)
    rng = np.random.default_rng(RANDOM_STATE)
    scores = []
    for i in range(X_ref.shape[1]):
        X_perturbed = X_ref.copy()
        rng.shuffle(X_perturbed[:, i])
        perturbed_pred = np.argmax(model.predict(X_perturbed, verbose=0), axis=1)
        scores.append(float(np.mean(perturbed_pred != base_pred)))
    order = np.argsort(scores)[::-1]
    print("Approximate feature importances (permutation, descending):")
    for i in order:
        print(f"  {FEATURE_NAMES[i]:<22} {scores[i]:.3f}")


def _save(model: keras.Model, scaler: StandardScaler, encoder: LabelEncoder,
          path_prefix: str, n_windows: int) -> None:
    model.save(f"{path_prefix}.keras")
    import joblib
    joblib.dump({"scaler": scaler, "encoder": encoder, "feature_names": FEATURE_NAMES},
                f"{path_prefix}_preproc.joblib")
    print(f"Saved model to {path_prefix}.keras and preprocessing "
          f"(scaler + label encoder) to {path_prefix}_preproc.joblib "
          f"(trained on all {n_windows} windows).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train an activity classifier (TF/Keras) with an honest session-grouped split."
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--model", default="activity_model_tf",
                         help="output path prefix (writes <prefix>.keras and <prefix>_preproc.joblib)")
    args = parser.parse_args()

    try:
        with open(args.dataset, encoding="utf-8") as dataset_file:
            data = json.load(dataset_file)
    except (OSError, ValueError) as error:
        print(f"could not read dataset {args.dataset}: {error}", file=sys.stderr)
        sys.exit(1)

    windows = data.get("windows", [])
    if not windows:
        print("dataset has no windows, run fetch_dataset.py first", file=sys.stderr)
        sys.exit(1)

    X_raw = np.array([_features(w["readings"]) for w in windows], dtype=float)
    y_raw = np.array([w["label"] for w in windows])
    groups = np.array([w["session_id"] for w in windows])

    classes = sorted(set(y_raw.tolist()))
    per_class = Counter(y_raw.tolist())
    sessions_per_class = {c: len(set(groups[y_raw == c].tolist())) for c in classes}
    n_windows = len(windows)
    n_sessions = len(set(groups.tolist()))

    encoder = LabelEncoder()
    encoder.fit(classes)
    y = encoder.transform(y_raw)

    print(f"Loaded {n_windows} windows, {len(classes)} classes, {n_sessions} session(s).")
    print("Windows / sessions per class:")
    for c in classes:
        print(f"  {c:<20} {per_class[c]:>5} windows   {sessions_per_class[c]:>2} session(s)")
    print()

    single_session_classes = [c for c in classes if sessions_per_class[c] < 2]
    if single_session_classes:
        print("!" * 72)
        print("Warning: these classes have windows from only one session:")
        for c in single_session_classes:
            print(f"    - {c}")
        print("A session-grouped split puts all of a class's windows on one side of the")
        print("split, so the model is tested on an environment it either always saw or")
        print("never saw. Any score for these classes is not trustworthy.")
        print("!" * 72)
        print()

    n_classes = len(classes)

    # --- honest evaluation requires at least two sessions to split on ---
    if n_sessions < 2:
        print("Only one session in the whole dataset. An honest held-out evaluation is")
        print("impossible, any split would leak. Training on all data and saving the")
        print("model, but reporting no accuracy. Go collect more labelled sessions.")
        print()
        scaler = StandardScaler().fit(X_raw)
        model = _new_model(X_raw.shape[1], n_classes)
        _fit(model, scaler.transform(X_raw), y)  # no validation split available
        _print_importances(model, scaler, scaler.transform(X_raw))
        print()
        _save(model, scaler, encoder, args.model, n_windows)
        return

    splitter = GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
    train_idx, test_idx = next(splitter.split(X_raw, y, groups))

    train_sessions = sorted(set(groups[train_idx].tolist()))
    test_sessions = sorted(set(groups[test_idx].tolist()))
    print(f"Train: {len(train_idx)} windows from sessions {train_sessions}")
    print(f"Test : {len(test_idx)} windows from sessions {test_sessions}")
    print("(Split by session, so these are entirely separate recordings.)")
    print()

    # Fit the scaler on TRAIN ONLY. Fitting on all data would leak test
    # statistics into training, same spirit as the grouped split itself.
    scaler = StandardScaler().fit(X_raw[train_idx])
    X_train = scaler.transform(X_raw[train_idx])
    X_test = scaler.transform(X_raw[test_idx])

    model = _new_model(X_raw.shape[1], n_classes)
    _fit(model, X_train, y[train_idx], X_test, y[test_idx])

    y_true = y[test_idx]
    y_pred = np.argmax(model.predict(X_test, verbose=0), axis=1)

    labels_encoded = list(range(n_classes))
    cm = confusion_matrix(y_true, y_pred, labels=labels_encoded)
    _print_confusion(cm, classes)
    print()
    print("Per-class precision / recall / support (held-out sessions):")
    print(classification_report(y_true, y_pred, labels=labels_encoded,
                                 target_names=classes, zero_division=0))

    accuracy = accuracy_score(y_true, y_pred)
    print(f"Overall accuracy on held-out sessions: {accuracy:.3f}")
    print()

    # Final artifact: retrain on everything so the saved model uses all the data.
    final_scaler = StandardScaler().fit(X_raw)
    X_all = final_scaler.transform(X_raw)
    final_model = _new_model(X_raw.shape[1], n_classes)
    _fit(final_model, X_all, y)  # no held-out set left, so no early stopping here
    _print_importances(final_model, final_scaler, X_all)
    print()

    # --- the blunt part ---
    print("=" * 72)
    print("what these numbers mean (read this before trusting anything):")

    tested = set(y_true.tolist())
    untested = [classes[c] for c in range(n_classes) if c not in tested]
    provisional = [c for c in classes if per_class[c] < PROVISIONAL_MIN_WINDOWS]
    flagged = False

    if accuracy > SUSPICIOUS_ACCURACY:
        flagged = True
        print(f"- {accuracy:.1%} accuracy is suspicious at this data volume, not a")
        print("  success, more so for a neural net than for a forest. With only a few")
        print("  sessions, a dense network keys on each session's environmental signature")
        print("  (node placement, RF multipath, the room's audio floor, rssi offset)")
        print("  which is constant through a session and rides along with the label. The")
        print("  grouped split kills window-level leakage but NOT this per-session confound,")
        print("  and dropout/early-stopping only slow the memorization, they don't stop it.")
        print("  Believe it only after many sessions per class, ideally recorded in")
        print("  different rooms and node placements.")
    if provisional:
        flagged = True
        print(f"- Provisional classes (<{PROVISIONAL_MIN_WINDOWS} windows): "
              f"{', '.join(provisional)}.")
        print("  Too few windows for a stable estimate, treat as directional only.")
    if untested:
        flagged = True
        print(f"- No test evidence at all for: {', '.join(untested)}.")
        print("  These classes never landed in the held-out session(s); their report rows")
        print("  are empty. The model may still predict them, untested.")
    if single_session_classes:
        flagged = True
        print(f"- Single-session classes: {', '.join(single_session_classes)}. Results")
        print("  not trustworthy (see the warning above).")
    if not flagged:
        print("- No automatic red flags fired, but small-data caveats always apply.")
        print("  Confirm with more sessions, in more rooms, before relying on this.")
    print("=" * 72)
    print()

    _save(final_model, final_scaler, encoder, args.model, n_windows)


if __name__ == "__main__":
    main()