import json
import joblib
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import tensorflow as tf
import keras
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import LabelEncoder, StandardScaler
from keras import layers

from train_activity import FEATURE_NAMES, _features

TEST_SIZE = 0.25
RANDOM_STATE = 0
MAX_EPOCHS = 200
MAX_MISCLASSIFICATIONS = 10

# Order matters: it lines up with the feature vector built in _features().
FEATURE_NAMES = [
    "motion_mean", "motion_std", "motion_min", "motion_max", "motion_range",
    "motion_mad", "motion_crossings_0.2",
    "audio_mean", "audio_std", "audio_min", "audio_max", "audio_range", "audio_mad",
    "presence_frac", "rssi_mean",
]

tf.random.set_seed(RANDOM_STATE)


def build_model(n_features, n_classes):
    model = keras.models.Sequential([
        keras.Input(shape=(n_features,)),
        layers.Dense(64, activation='relu'),
        layers.Dropout(0.4),
        layers.Dense(32, activation='relu'),
        layers.Dropout(0.3),
        layers.Dense(n_classes, activation='softmax')
    ])

    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=1e-3),
        loss="sparse_categorical_crossentropy",
        metrics=['accuracy'],
    )

    return model


def train_model(model, X_train, y_train, epochs):
    return model.fit(
        X_train,
        y_train,
        epochs=epochs,
        batch_size=32,
        shuffle=True,
        verbose=1,
    )


def main():
    with open("dataset.json", encoding="utf-8") as dataset_file:
        windows = json.load(dataset_file).get("windows", [])
    if not windows:
        raise ValueError("dataset.json contains no windows to evaluate")

    order = np.random.default_rng(RANDOM_STATE).permutation(len(windows))
    windows = [windows[index] for index in order]
    X_raw = np.asarray([_features(window["readings"]) for window in windows], dtype=float)
    labels = np.asarray([window["label"] for window in windows])
    groups = np.asarray([window["session_id"] for window in windows])
    encoder = LabelEncoder().fit(labels)
    y = encoder.transform(labels)

    splitter = StratifiedGroupKFold(
        n_splits=2, shuffle=True, random_state=RANDOM_STATE
    )
    train_indices, test_indices = next(splitter.split(X_raw, y, groups))
    all_classes = set(range(len(encoder.classes_)))
    missing_train = all_classes - set(y[train_indices])
    missing_test = all_classes - set(y[test_indices])
    if missing_train or missing_test:
        missing_train_names = [encoder.classes_[index] for index in sorted(missing_train)]
        missing_test_names = [encoder.classes_[index] for index in sorted(missing_test)]
        raise ValueError(
            "Session-grouped split must include every class in both sets. "
            f"Missing from train: {missing_train_names}; "
            f"missing from test: {missing_test_names}. "
            "Collect more separate sessions for each class."
        )

    print(f"Train sessions: {sorted(set(groups[train_indices]))}")
    print(f"Test sessions: {sorted(set(groups[test_indices]))}")
    scaler = StandardScaler().fit(X_raw[train_indices])
    X_train = scaler.transform(X_raw[train_indices])
    X_test = scaler.transform(X_raw[test_indices])

    model = build_model(len(FEATURE_NAMES), len(encoder.classes_))
    train_model(model, X_train, y[train_indices], 8)
    model.save('csi_model.keras')
    # Persist the fitted scaler and class order so the saved model is usable at
    # inference time. raw features must be scaled identically and prediction
    # indices mapped back to labels the same way they were during training.
    joblib.dump(
        {"scaler": scaler, "classes": encoder.classes_.tolist()},
        "csi_model_meta.joblib",
    )
    prediction_probabilities = model.predict(X_test, verbose=0)
    predicted_labels = np.argmax(prediction_probabilities, axis=1)
    class_indices = np.arange(len(encoder.classes_))
    confusion = confusion_matrix(y[test_indices], predicted_labels, labels=class_indices)
    print("Confusion matrix (rows = actual, columns = predicted):")
    print(confusion)

    misclassified = np.flatnonzero(predicted_labels != y[test_indices])
    print(f"\nMisclassified test windows: {len(misclassified)}")
    if len(misclassified) == 0:
        print("No misclassifications in the held-out set.")
    else:
        for prediction_index in misclassified[:MAX_MISCLASSIFICATIONS]:
            window = windows[test_indices[prediction_index]]
            confidence = prediction_probabilities[prediction_index, predicted_labels[prediction_index]]
            print(
                f"  actual={str(encoder.classes_[y[test_indices[prediction_index]]])!r}, "
                f"predicted={str(encoder.classes_[predicted_labels[prediction_index]])!r}, "
                f"confidence={confidence:.1%}, session={window['session_id']}, "
                f"zone={window['zone']}, start={window['start_ts']}"
            )

    print(f"\nActual feature values for all {len(windows)} dataset windows:")
    print(f"Feature order: {', '.join(FEATURE_NAMES)}")
    for window_index, (window, feature_values) in enumerate(zip(windows, X_raw), start=1):
        values = np.array2string(feature_values, precision=4, separator=", ")
        print(
            f"  {window_index:03d} label={window['label']!r}, "
            f"session={window['session_id']}, zone={window['zone']}, "
            f"start={window['start_ts']}, values={values}"
        )

    plt.figure(figsize=(7, 6))
    sns.heatmap(
        confusion,
        annot=True,
        fmt="d",
        cmap="Blues",
        cbar=False,
        xticklabels=encoder.classes_,
        yticklabels=encoder.classes_,
    )
    plt.xlabel("Predicted label")
    plt.ylabel("Actual label")
    plt.title("CSI Activity Model Confusion Matrix (held-out sessions)")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()

