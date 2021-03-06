"""Includes a bunch of transformer for dataset."""

import numpy as np
import torch
from kgegrok.data import constants
from kgegrok.utils import deprecation
from kgegrok.stats.constants import StatisticsDimension
import kgedata
import kgekit


class CorruptionFlagGenerator(object):
  """Generates corrupted head/tail decision in uniform distribution.
    if used with bernoulli corruptor, it's Bernoulli Distribution based on tph.
    True means we will corrupt head."""

  def __init__(self, corruptor):
    self.corruptor = corruptor

  def __call__(self, batch):
    """return corruption flag and actual batch"""
    choices = self.corruptor(batch)
    return choices, batch


class NegativeBatchGenerator(object):
  """Process and sample an negative batch. Supports multiprocess from pytorch.
    Returns:
        Positive tensor with shape (batch_size, 3).
        Negative tensor with shape (batch_size, negative_samples, 3).
    """

  def __init__(self, negative_sampler):
    self.sampler = negative_sampler

  def __call__(self, batch_set):
    corrupt_head, batch = batch_set
    negative_batch = self.sampler(corrupt_head, batch)
    return batch, negative_batch


def _np_to_tensor(x):
  if x is None: return x
  # Input is an index to find relevant embeddings. We don't track them
  if type(x) == tuple:
    return tuple(map(_np_to_tensor, x))
  if type(x) == list:
    return list(map(_np_to_tensor, x))
  return torch.from_numpy(x).requires_grad_(False)


class LabelBatchGenerator(object):
  """Add data label (third element) for a sample."""

  def __init__(self, config, negative_batch_label_generator,
               positive_batch_label_generator):
    self._batch_size = config.batch_size

    self._negative_label_generator = negative_batch_label_generator
    self._positive_label_generator = positive_batch_label_generator
    # cache positive labels for a normal batch so we don't have to build them repeatly
    self._cached_pos_labels = positive_batch_label_generator(
        (self._batch_size,))

  def __call__(self, sample):
    """Add data label for (batch, negative_batch).
        positive batch shape: (batch_size, 3)
        negative batch shape: (batch_size, negative_samples, 3).
        positive label batch shape: (batch_size,)
        negative label batch shape: (negative_samples*batch_size,).
        """
    batch, negative_batch = sample
    batch_size = batch.shape[0]

    neg_labels = self._negative_label_generator(negative_batch)
    pos_labels = self._positive_label_generator(
        (batch_size,
        )) if batch_size < self._batch_size else self._cached_pos_labels
    return batch, negative_batch, (pos_labels, neg_labels.ravel())


def tensor_transform(sample):
  """Returns batch, negative_batch by the tensor."""
  return _np_to_tensor(sample)


def _apply_tensor_float(labels):
  return labels.float() if labels is not None else labels


def labels_type_transform(sample):
  """Returns the label transformed. As models requires a DoubleTensor"""

  batch, negative_batch, labels = sample
  labels = [_apply_tensor_float(l) for l in labels]
  return batch, negative_batch, labels


def none_label_batch_generator(sample):
  """Generates a None for labels."""
  batch, negative_batch = sample
  return batch, negative_batch, None


class TripleTileGenerator(object):
  """Process triples and put them into a tiled but flat numpy array.
    Args:
        config: config object for reading dimension information
        triple_source: triple source function
    Returns:
        Positive tensor with shape (batch_size * varied_size, 1, 3).
            varied_size will depends on testing dimension, num_entity and num_relation.
        Original batch from PyTorch,
        Splits split points
    """

  def __init__(self, config, triple_source):
    self.config = config
    self.triple_source = triple_source

  def __call__(self, batch):
    """process a mini-batch."""
    sampled, splits = kgedata.expand_triple_batch(
        batch, self.triple_source.num_entity, self.triple_source.num_relation,
        (self.config.report_dimension & StatisticsDimension.SEPERATE_ENTITY) or
        (self.config.report_dimension & StatisticsDimension.COMBINED_ENTITY),
        self.config.report_dimension & StatisticsDimension.RELATION)

    return sampled, batch, splits


def test_batch_transform(sample):
  """Generates None and put things into Tensor."""
  tiled, batch, splits = sample

  tiled = _np_to_tensor(tiled)
  return (tiled, None, None), batch, splits


class BatchMasker(object):
  """Mask the batch given parameters."""

  def __init__(self, masks):
    self._masks = masks

  def __call__(self, batch):
    """process mini-batch."""
    mi = iter(self._masks)
    return tuple(
        map(lambda x: None if next(mi) else x, batch))


def label_prediction_collate(sample):
  """Add all positive labels for sample.
    """
  deprecation("Not tested anymore", since="0.3.0")

  tiled, batch, splits = sample

  labels_shape = (tiled.shape[0])
  labels = np.full(labels_shape, 1, dtype=np.int64)

  return tiled, batch, splits, labels


class NumpyCollate(object):
  """Process triples and put them into a triple index.
    Returns:
        Positive tensor with shape (batch_size, 1, 3).
    """

  def __init__(self, transform=None):
    deprecation("Not tested anymore", since="0.3.0")
    self.transform = transform

  def __call__(self, batch: constants.TripleIndexList):
    """process a mini-batch."""
    batch_size = len(batch)
    if self.transform:
      batch = self.transform(batch)
    batch = np.array(batch, dtype=np.int64)[:, np.newaxis, :]
    return batch


class BreakdownCollator(object):

  def __init__(self, config):
    deprecation("Not tested anymore", since="0.3.0")
    self.config = config

  def __call__(self, sample):
    batch, negative_batch, labels = sample
    if labels is not None:
      labels = data.np_to_tensor(labels, self.config.enable_cuda)
    batch = data.convert_triple_tuple_to_torch(
        data.get_triples_from_batch(batch), self.config, False)
    negative_batch = data.convert_triple_tuple_to_torch(
        data.get_triples_from_batch(negative_batch), self.config, False)
    return batch, negative_batch, labels


class LiteralCollate(object):

  def __init__(self,
               source,
               negative_sampler,
               literals,
               transforms,
               sample_negative_for_non_triples=False):
    deprecation("WIP", since="0.3.0")
    self.source = source
    self.negative_sampler = negative_sampler
    self.literals = literals
    self.sample_negative_for_non_triples = sample_negative_for_non_triples
    self.transforms = transforms


class OrderedTripleTransform(object):
  """Reformat a triple index into list.

    Args:
        triple_order (str): Desired triple order in list.
    """

  def __init__(self, triple_order):
    deprecation("Input is changed to numpy array.", since="0.3.0")
    kgekit.utils.assert_triple_order(triple_order)
    self.triple_order = triple_order

  def __call__(self, sample):
    vec = []
    for o in self.triple_order:
      if o == 'h':
        vec.append(sample.head)
      elif o == 'r':
        vec.append(sample.relation)
      elif o == 't':
        vec.append(sample.tail)

    return vec


class OrderedTripleListTransform(object):
  """Reformat a triple index into list.

    Args:
        triple_order (str): Desired triple order in list.
    """

  def __init__(self, triple_order):
    deprecation("Input is changed to numpy array.", since="0.3.0")
    kgekit.utils.assert_triple_order(triple_order)
    self.triple_order = triple_order

  def __call__(self, samples):
    batch_size = len(samples)
    batch = np.empty((batch_size, constants.TRIPLE_LENGTH), dtype=np.int64)
    for i in range(batch_size):
      for o in self.triple_order:
        t = samples[i]
        if o == 'h':
          batch[i, 0] = t.head
        elif o == 'r':
          batch[i, 1] = t.relation
        elif o == 't':
          batch[i, 2] = t.tail

    return batch


class FactTransform(object):
  """Returns a list of fact transformed. For example bert.

    Args:
        triple_order (str): Desired triple order in list.
    """

  def __init__(self, triple_order):
    deprecation("Input is changed to numpy array.", since="0.3.0")
    kgekit.utils.assert_triple_order(triple_order)
    self.triple_order = triple_order

  def __call__(self, samples):
    batch_size = len(samples)
    batch = np.empty(
        (batch_size, constants.NUM_POSITIVE_INSTANCE, constants.TRIPLE_LENGTH),
        dtype=np.int64)
    for i in range(batch_size):
      for o in self.triple_order:
        t = samples[i]
        if o == 'h':
          batch[i, 0, 0] = t.head
        elif o == 'r':
          batch[i, 0, 1] = t.relation
        elif o == 't':
          batch[i, 0, 2] = t.tail

    return batch
