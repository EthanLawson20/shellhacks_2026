"""Train an activity classifier on windows produced by fetch_dataset.py.

The whole trick to an honest number here is the split. Windows overlap and come
in long runs from the same recording session, so a random train/test split puts
near-duplicate windows on both sides — the accuracy looks great and means
nothing. We split by session_id (GroupShuffleSplit) so no session is on both
sides. Even that only stops *window-level* leakage; with few sessions the model
can still learn each session's environmental signature. The summary says so.

    python train_activity.py --dataset dataset.json --model activity_model.joblib

Deps: numpy, scikit-learn, joblib (see requirements-ml.txt).
"""
import argparse
import json
import sys
from collections import Counter

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import GroupShuffleSplit

MOTION_CROSS_THRESHOLD = 0.2
TEST_SIZE = 0.25
RANDOM_STATE = 0
PROVISIONAL_MIN_WINDOWS = 50
SUSPICIOUS_ACCURACY = 0.95

# Order matters: it lines up with the feature vector built in _features().
FEATURE_NAMES = [
    "motion_mean", "motion_std", "motion_min", "motion_max", "motion_range",
    "motion_mad", "motion_crossings_0.2",
    "audio_mean", "audio_std", "audio_min", "audio_max", "audio_range", "audio_mad",
    "presence_frac", "rssi_mean",
]


def _six_stats(x: np.ndarray) -> list:
    """mean, std, min, max, range, mean-abs-diff between consecutive samples."""
    if x.size == 0:
        return [0.0] * 6
    mad = float(np.mean(np.abs(np.diff(x)))) if x.size > 1 else 0.0
    return [float(x.mean()), float(x.std()), float(x.min()), float(x.max()),
            float(x.max() - x.min()), mad]


def _up_crossings(x: np.ndarray, threshold: float) -> int:
    """Number of times the series rises through the threshold (a motion burst)."""
    if x.size < 2:
        return 0
    return int(np.count_nonzero((x[:-1] <= threshold) & (x[1:] > threshold)))


def _features(readings: list) -> list:
    """Turn one window's readings into the fixed feature vector (see FEATURE_NAMES)."""
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


def _print_importances(clf: RandomForestClassifier) -> None:
    order = np.argsort(clf.feature_importances_)[::-1]
    print("Feature importances (descending):")
    for i in order:
        print(f"  {FEATURE_NAMES[i]:<22} {clf.feature_importances_[i]:.3f}")


def _new_classifier() -> RandomForestClassifier:
    return RandomForestClassifier(
        n_estimators=300, random_state=RANDOM_STATE,
        class_weight="balanced", n_jobs=-1,
    )


def _save(clf: RandomForestClassifier, path: str, n_windows: int) -> None:
    bundle = {"model": clf, "feature_names": FEATURE_NAMES, "classes": list(clf.classes_)}
    joblib.dump(bundle, path)
    print(f"Saved model bundle to {path} "
          f"(a RandomForest retrained on all {n_windows} windows, plus feature names).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train an activity classifier with an honest session-grouped split."
    )
    parser.add_argument("--dataset", default="dataset.json")
    parser.add_argument("--model", default="activity_model.joblib")
    args = parser.parse_args()

    try:
        with open(args.dataset, encoding="utf-8") as dataset_file:
            data = json.load(dataset_file)
    except (OSError, ValueError) as error:
        print(f"could not read dataset {args.dataset}: {error}", file=sys.stderr)
        sys.exit(1)

    windows = data.get("windows", [])
    if not windows:
        print("dataset has no windows — run fetch_dataset.py first", file=sys.stderr)
        sys.exit(1)

    X = np.array([_features(w["readings"]) for w in windows], dtype=float)
    y = np.array([w["label"] for w in windows])
    groups = np.array([w["session_id"] for w in windows])

    classes = sorted(set(y.tolist()))
    per_class = Counter(y.tolist())
    sessions_per_class = {c: len(set(groups[y == c].tolist())) for c in classes}
    n_windows = len(windows)
    n_sessions = len(set(groups.tolist()))

    print(f"Loaded {n_windows} windows, {len(classes)} classes, {n_sessions} session(s).")
    print("Windows / sessions per class:")
    for c in classes:
        print(f"  {c:<20} {per_class[c]:>5} windows   {sessions_per_class[c]:>2} session(s)")
    print()

    single_session_classes = [c for c in classes if sessions_per_class[c] < 2]
    if single_session_classes:
        print("!" * 72)
        print("WARNING: these classes have windows from only ONE session:")
        for c in single_session_classes:
            print(f"    - {c}")
        print("A session-grouped split puts all of a class's windows on ONE side of the")
        print("split, so the model is tested on an environment it either always saw or")
        print("never saw. Any score for these classes is NOT trustworthy.")
        print("!" * 72)
        print()

    # --- honest evaluation requires at least two sessions to split on ---
    if n_sessions < 2:
        print("Only one session in the whole dataset. An honest held-out evaluation is")
        print("IMPOSSIBLE — any split would leak. Training on all data and saving the")
        print("model, but reporting NO accuracy. Go collect more labelled sessions.")
        print()
        clf = _new_classifier()
        clf.fit(X, y)
        _print_importances(clf)
        print()
        _save(clf, args.model, n_windows)
        return

    splitter = GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
    train_idx, test_idx = next(splitter.split(X, y, groups))

    train_sessions = sorted(set(groups[train_idx].tolist()))
    test_sessions = sorted(set(groups[test_idx].tolist()))
    print(f"Train: {len(train_idx)} windows from sessions {train_sessions}")
    print(f"Test : {len(test_idx)} windows from sessions {test_sessions}")
    print("(Split by session, so these are entirely separate recordings.)")
    print()

    clf = _new_classifier()
    clf.fit(X[train_idx], y[train_idx])
    y_true = y[test_idx]
    y_pred = clf.predict(X[test_idx])

    cm = confusion_matrix(y_true, y_pred, labels=classes)
    _print_confusion(cm, classes)
    print()
    print("Per-class precision / recall / support (held-out sessions):")
    print(classification_report(y_true, y_pred, labels=classes, zero_division=0))

    accuracy = accuracy_score(y_true, y_pred)
    print(f"Overall accuracy on held-out sessions: {accuracy:.3f}")
    print()

    # Final artifact: retrain on everything so the saved model uses all the data.
    final = _new_classifier()
    final.fit(X, y)
    _print_importances(final)
    print()

    # --- the blunt part ---
    print("=" * 72)
    print("WHAT THESE NUMBERS MEAN — read this before trusting anything:")

    tested = set(y_true.tolist())
    untested = [c for c in classes if c not in tested]
    provisional = [c for c in classes if per_class[c] < PROVISIONAL_MIN_WINDOWS]
    flagged = False

    if accuracy > SUSPICIOUS_ACCURACY:
        flagged = True
        print(f"- {accuracy:.1%} accuracy is SUSPICIOUS at this data volume, not a")
        print("  success. With only a few sessions a RandomForest keys on each session's")
        print("  environmental signature — node placement, RF multipath, the room's audio")
        print("  floor, rssi offset — which is constant through a session and rides along")
        print("  with the label. The grouped split kills window-level leakage but NOT this")
        print("  per-session confound. Believe it only after many sessions per class,")
        print("  ideally recorded in different rooms and node placements.")
    if provisional:
        flagged = True
        print(f"- Provisional classes (<{PROVISIONAL_MIN_WINDOWS} windows): "
              f"{', '.join(provisional)}.")
        print("  Too few windows for a stable estimate — treat as directional only.")
    if untested:
        flagged = True
        print(f"- No test evidence at all for: {', '.join(untested)}.")
        print("  These classes never landed in the held-out session(s); their report rows")
        print("  are empty. The model may still predict them, untested.")
    if single_session_classes:
        flagged = True
        print(f"- Single-session classes: {', '.join(single_session_classes)} — results")
        print("  not trustworthy (see the warning above).")
    if not flagged:
        print("- No automatic red flags fired, but small-data caveats always apply.")
        print("  Confirm with more sessions, in more rooms, before relying on this.")
    print("=" * 72)
    print()

    _save(final, args.model, n_windows)


if __name__ == "__main__":
    main()
