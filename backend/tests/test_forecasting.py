"""Forecasting: feature engineering, windowing and a real training run.

The dataset tests are the important ones. They assert the two properties that
silently destroy a time-series model if violated — no lookahead in the scaler,
and a chronological split — and neither would surface as an error at runtime.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.forecasting.dataset import (
    FEATURE_COLUMNS,
    MinMaxScaler,
    build_features,
    latest_window,
    prepare_dataset,
)
from app.services.forecasting.model import (
    directional_accuracy,
    evaluate_forecast,
    mape,
    rmse,
    tensorflow_available,
)

requires_tensorflow = pytest.mark.skipif(
    not tensorflow_available(), reason="TensorFlow is not installed"
)


class TestScaler:
    def test_round_trip_is_lossless(self):
        values = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]])
        scaler = MinMaxScaler()
        scaled = scaler.fit_transform(values)
        np.testing.assert_allclose(scaler.inverse_transform(scaled), values)

    def test_scales_into_the_unit_range(self):
        values = np.array([[5.0], [10.0], [15.0]])
        scaled = MinMaxScaler().fit_transform(values)
        assert scaled.min() == pytest.approx(0.0)
        assert scaled.max() == pytest.approx(1.0)

    def test_constant_column_does_not_divide_by_zero(self):
        scaled = MinMaxScaler().fit_transform(np.array([[7.0], [7.0], [7.0]]))
        assert np.isfinite(scaled).all()

    def test_transform_before_fit_raises(self):
        with pytest.raises(RuntimeError):
            MinMaxScaler().transform(np.array([[1.0]]))

    def test_serialises_and_restores(self):
        values = np.array([[1.0, 2.0], [3.0, 4.0]])
        original = MinMaxScaler().fit(values)
        restored = MinMaxScaler.from_dict(original.to_dict())
        np.testing.assert_allclose(
            original.transform(values), restored.transform(values)
        )


class TestFeatures:
    def test_all_declared_features_are_produced(self, ohlcv):
        features = build_features(ohlcv)
        for column in FEATURE_COLUMNS:
            assert column in features.columns

    def test_no_infinities_survive(self, ohlcv):
        assert not np.isinf(build_features(ohlcv).to_numpy(dtype=float)).any()

    def test_features_are_scale_invariant(self, ohlcv_factory):
        """A ₹100 stock and a ₹10,000 stock must produce the same features.

        This is the property that lets one architecture serve every ticker; if
        it breaks, the model has learned a price level instead of a pattern.
        """
        cheap = ohlcv_factory(rows=200, start_price=100.0, seed=3)
        expensive = ohlcv_factory(rows=200, start_price=10_000.0, seed=3)

        a = build_features(cheap).dropna().to_numpy(dtype=float)
        b = build_features(expensive).dropna().to_numpy(dtype=float)
        np.testing.assert_allclose(a, b, rtol=1e-6, atol=1e-8)

    def test_log_return_matches_definition(self, ohlcv):
        features = build_features(ohlcv)
        expected = np.log(ohlcv["close"].iloc[10] / ohlcv["close"].iloc[9])
        assert features["log_return"].iloc[10] == pytest.approx(expected)


class TestPrepareDataset:
    def test_shapes_line_up(self, ohlcv):
        data = prepare_dataset(ohlcv, sequence_length=30, validation_split=0.2)
        assert data.x_train.shape[1] == 30
        assert data.x_train.shape[2] == len(FEATURE_COLUMNS)
        assert len(data.x_train) == len(data.y_train)
        assert len(data.x_validation) == len(data.y_validation)

    def test_split_is_chronological(self, ohlcv):
        """Validation windows must come strictly after training windows."""
        data = prepare_dataset(ohlcv, sequence_length=20, validation_split=0.2)
        total = len(data.x_train) + len(data.x_validation)
        assert data.split_index == len(data.x_train)
        assert total == len(build_features(ohlcv).dropna()) - 20

    def test_scaler_is_not_fitted_on_validation_data(self, ohlcv):
        """The scaler must not have seen the validation range.

        Fitting on everything is the classic leak: it looks like a better model
        offline and cannot be reproduced live. Asserted by checking that the
        fitted minimum matches the training slice, not the whole series.
        """
        sequence_length = 20
        data = prepare_dataset(ohlcv, sequence_length=sequence_length, validation_split=0.3)

        features = build_features(ohlcv).dropna()
        values = features[FEATURE_COLUMNS].to_numpy(dtype=float)
        train_rows = data.split_index + sequence_length

        np.testing.assert_allclose(
            data.feature_scaler.minimum, np.nanmin(values[:train_rows], axis=0)
        )
        # And it must differ from a scaler fitted on everything, or the test
        # would pass trivially.
        assert not np.allclose(
            data.feature_scaler.minimum, np.nanmin(values, axis=0)
        ) or train_rows == len(values)

    def test_too_little_history_raises(self, short_ohlcv):
        with pytest.raises(ValueError, match="clean rows"):
            prepare_dataset(short_ohlcv, sequence_length=60)

    def test_scaled_values_stay_in_range_for_training_split(self, ohlcv):
        data = prepare_dataset(ohlcv, sequence_length=20, validation_split=0.2)
        assert data.x_train.min() >= -1e-9
        assert data.x_train.max() <= 1 + 1e-9


class TestLatestWindow:
    def test_shape_is_a_single_batch(self, ohlcv):
        data = prepare_dataset(ohlcv, sequence_length=25)
        window = latest_window(data.feature_frame, data.feature_scaler, 25)
        assert window.shape == (1, 25, len(FEATURE_COLUMNS))

    def test_insufficient_rows_raises(self, ohlcv):
        data = prepare_dataset(ohlcv, sequence_length=25)
        with pytest.raises(ValueError):
            latest_window(data.feature_frame.tail(5), data.feature_scaler, 25)


class TestMetrics:
    def test_perfect_prediction_scores_perfectly(self):
        actual = np.array([0.01, -0.02, 0.03])
        result = evaluate_forecast(actual, actual)
        assert result["rmse"] == pytest.approx(0.0)
        assert result["directionalAccuracy"] == pytest.approx(1.0)

    def test_directional_accuracy_counts_signs_only(self):
        actual = np.array([1.0, -1.0, 1.0, -1.0])
        predicted = np.array([5.0, -5.0, -5.0, 5.0])  # first two right
        assert directional_accuracy(actual, predicted) == pytest.approx(0.5)

    def test_skill_score_is_positive_when_beating_the_baseline(self):
        actual = np.array([0.01, 0.02, -0.01, 0.015])
        good = actual * 0.9  # close to the truth
        assert evaluate_forecast(actual, good)["skillScore"] > 0

    def test_skill_score_is_negative_when_worse_than_predicting_nothing(self):
        actual = np.array([0.01, 0.02, -0.01, 0.015])
        terrible = -actual * 5
        assert evaluate_forecast(actual, terrible)["skillScore"] < 0

    def test_mape_ignores_near_zero_denominators(self):
        assert np.isfinite(mape(np.array([0.0, 0.0]), np.array([1.0, 1.0])))

    def test_rmse_is_non_negative(self):
        assert rmse(np.array([1.0, 2.0]), np.array([2.0, 1.0])) >= 0


@requires_tensorflow
class TestTrainingRun:
    """A real end-to-end training run on synthetic data.

    Kept deliberately small (a few epochs on a short window) so it stays in the
    normal test suite rather than becoming a nightly job.
    """

    def test_train_and_forecast_end_to_end(self, app, ohlcv, tmp_path):
        from app.services.forecasting import forecast_symbol, train_symbol

        app.config["MODEL_DIR"] = tmp_path / "models"
        app.config["MODEL_DIR"].mkdir(parents=True, exist_ok=True)
        app.config.update(SEQUENCE_LENGTH=20, TRAIN_EPOCHS=2, MIN_TRAINING_ROWS=100)

        metadata = train_symbol("TEST", ohlcv, force=True)
        assert metadata.symbol == "TEST"
        assert metadata.training_rows > 0
        assert 0.0 <= metadata.metrics["directionalAccuracy"] <= 1.0
        assert "baselineRmse" in metadata.metrics

        payload = forecast_symbol("TEST", ohlcv, horizon=3)
        assert len(payload["forecast"]) == 3
        assert payload["forecast"][0]["step"] == 1

        for point in payload["forecast"]:
            assert point["lowerBound"] < point["predictedClose"] < point["upperBound"]

        # Uncertainty must grow with the horizon, not stay flat.
        first = payload["forecast"][0]
        last = payload["forecast"][-1]
        assert (last["upperBound"] - last["lowerBound"]) > (
            first["upperBound"] - first["lowerBound"]
        )

    def test_model_is_reused_until_stale(self, app, ohlcv, tmp_path):
        from app.services.forecasting import train_symbol

        app.config["MODEL_DIR"] = tmp_path / "models"
        app.config["MODEL_DIR"].mkdir(parents=True, exist_ok=True)
        app.config.update(SEQUENCE_LENGTH=20, TRAIN_EPOCHS=1, MIN_TRAINING_ROWS=100)

        first = train_symbol("REUSE", ohlcv, force=True)
        second = train_symbol("REUSE", ohlcv)  # should hit the cache
        assert first.trained_at == second.trained_at
