from keras_core.losses import loss
from keras_core import operations as ops
from keras_core.api_export import keras_core_export
from keras_core.metrics.metric import Metric
from keras_core import initializers
from keras_core import backend


def reduce_to_samplewise_values(values, sample_weight, reduce_fn, dtype):
    mask = getattr(values, "_keras_mask", None)
    values = ops.cast(values, dtype=dtype)
    if sample_weight is not None:
        sample_weight = ops.cast(sample_weight, dtype=dtype)
        if mask is not None:
            sample_weight = loss.apply_mask(sample_weight, mask, dtype=dtype, reduction="sum")
        # Update dimensions of weights to match with values if possible.
        values, sample_weight = loss.squeeze_to_same_rank(
            values, sample_weight
        )
        # Reduce values to same ndim as weight array
        weight_ndim = len(sample_weight.shape)
        values_ndim = len(values.shape)
        if values_ndim > weight_ndim:
            values = reduce_fn(
                values, axis=list(range(weight_ndim, values_ndim))
            )
        values = values * sample_weight
    
    values_ndim = len(values.shape)
    if values_ndim > 1:
        return reduce_fn(values, axis=list(range(1, values_ndim)))
    return values, sample_weight


@keras_core_export("keras_core.metrics.Sum")
class Sum(Metric):
    """Compute the (weighted) sum of the given values.

    For example, if `values` is `[1, 3, 5, 7]` then their sum is 16.
    If `sample_weight` was specified as `[1, 1, 0, 0]` then the sum would be 4.

    This metric creates one variable, `total`.
    This is ultimately returned as the sum value.

    Args:
        name: (Optional) string name of the metric instance.
        dtype: (Optional) data type of the metric result.

    Example:

    >>> m = metrics.Sum()
    >>> m.update_state([1, 3, 5, 7])
    >>> m.result()
    16.0
    """

    def __init__(self, name="sum", dtype=None):
        super().__init__(name=name, dtype=dtype)
        self.total = self.add_variable(shape=(), initializer=initializers.Zeros(), dtype=self.dtype)

    def update_state(self, values, sample_weight=None):
        values, _ = reduce_to_samplewise_values(values, sample_weight, reduce_fn=ops.sum, dtype=self.dtype)
        self.total.assign(self.total + ops.sum(values))

    def reset_state(self):
        self.total.assign(0.)

    def result(self):
        return ops.identity(self.total)


@keras_core_export("keras_core.metrics.Mean")
class Mean(Metric):
    """Compute the (weighted) mean of the given values.

    For example, if values is `[1, 3, 5, 7]` then the mean is 4.
    If `sample_weight` was specified as `[1, 1, 0, 0]` then the mean would be 2.

    This metric creates two variables, `total` and `count`.
    The mean value returned is simply `total` divided by `count`.

    Args:
        name: (Optional) string name of the metric instance.
        dtype: (Optional) data type of the metric result.

    Example:

    >>> m = Mean()
    >>> m.update_state([1, 3, 5, 7])
    >>> m.result()
    4.0
    >>> m.reset_state()
    >>> m.update_state([1, 3, 5, 7], sample_weight=[1, 1, 0, 0])
    >>> m.result()
    2.0
    ```
    """
    def __init__(self, name="sum", dtype=None):
        super().__init__(name=name, dtype=dtype)
        self.total = self.add_variable(shape=(), initializer=initializers.Zeros(), dtype=self.dtype)
        self.count = self.add_variable(shape=(), initializer=initializers.Zeros(), dtype="int64")

    def update_state(self, values, sample_weight=None):
        values, sample_weight = reduce_to_samplewise_values(values, sample_weight, reduce_fn=ops.mean, dtype=self.dtype)
        self.total.assign(self.total + ops.sum(values))
        if sample_weight is not None:
            num_samples = ops.sum(ops.ones(shape=(values.shape[0],)) * sample_weight)
        else:
            num_samples = values.shape[0]
        self.count.assign(self.count + ops.cast(num_samples, dtype="int64"))

    def reset_state(self):
        self.total.assign(0.)
        self.count.assign(0)

    def result(self):
        return self.total / (ops.cast(self.count, dtype=self.dtype) + backend.epsilon())


@keras_core_export("keras_core.metrics.MeanMetricWrapper")
class MeanMetricWrapper(Mean):
    """Wrap a stateless metric function with the Mean metric.

    You could use this class to quickly build a mean metric from a function. The
    function needs to have the signature `fn(y_true, y_pred)` and return a
    per-sample loss array. `MeanMetricWrapper.result()` will return
    the average metric value across all samples seen so far.

    For example:

    ```python
    def mse(y_true, y_pred):
        return (y_true - y_pred) ** 2

    mse_metric = MeanMetricWrapper(fn=mse)
    ```

    Args:
        fn: The metric function to wrap, with signature
            `fn(y_true, y_pred, **kwargs)`.
        name: (Optional) string name of the metric instance.
        dtype: (Optional) data type of the metric result.
        **kwargs: Keyword arguments to pass on to `fn`.
    """

    def __init__(self, fn, name=None, dtype=None, **kwargs):
        super().__init__(name=name, dtype=dtype)
        self._fn = fn
        self._fn_kwargs = kwargs

    def update_state(self, y_true, y_pred, sample_weight=None):
        mask = getattr(y_pred, "_keras_mask", None)
        values = self._fn(y_true, y_pred, **self._fn_kwargs)
        if sample_weight is not None and mask is not None:
            sample_weight = loss.apply_mask(sample_weight, mask, dtype=self.dtype, reduction="sum")
        return super().update_state(values, sample_weight=sample_weight)

    def get_config(self):
        config = {
            k: v for k, v in self._fn_kwargs.items()
        }
        config["fn"] = self._fn
        base_config = super().get_config()
        return {**base_config.items(), **config.items()}

    @classmethod
    def from_config(cls, config):
        raise NotImplementedError