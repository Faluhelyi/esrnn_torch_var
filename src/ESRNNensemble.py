import os
import time
import random

import numpy as np
import pandas as pd

import torch
import torch.nn as nn
import torch.optim as optim

from copy import deepcopy
from pathlib import Path

from src.ESRNN import ESRNN

from src.utils_evaluation import owa


class ESRNNensemble(object):
    def __init__(self, num_splits = 1, max_epochs=15, batch_size=1, batch_size_test=128, freq_of_test=-1,
               learning_rate=1e-3, lr_scheduler_step_size=9, lr_decay=0.9,
               per_series_lr_multip=1.0, gradient_eps=1e-8, gradient_clipping_threshold=20,
               rnn_weight_decay=0, noise_std=0.001,
               level_variability_penalty=80,
               percentile=50, training_percentile=50, ensemble=False,
               cell_type='LSTM',
               state_hsize=40, dilations=[[1, 2], [4, 8]],
               add_nl_layer=False, seasonality=[4], input_size=4, output_size=8,
               frequency='D', max_periods=20, random_seed=1,
               device='cuda', root_dir='./'):
        super(ESRNNensemble, self).__init__()

        self.num_splits = num_splits
        self._fitted = False
        self.device = device

        esrnn = ESRNN(max_epochs=max_epochs, batch_size=batch_size, batch_size_test=batch_size_test, 
                          freq_of_test=freq_of_test, learning_rate=learning_rate,
                          lr_scheduler_step_size=lr_scheduler_step_size, lr_decay=lr_decay,
                          per_series_lr_multip=per_series_lr_multip,
                          gradient_eps=gradient_eps, gradient_clipping_threshold=gradient_clipping_threshold,
                          rnn_weight_decay=rnn_weight_decay, noise_std=noise_std,
                          level_variability_penalty=level_variability_penalty,
                          percentile=percentile,
                          training_percentile=training_percentile, ensemble=ensemble,
                          cell_type=cell_type,
                          state_hsize=state_hsize, dilations=dilations, add_nl_layer=add_nl_layer,
                          seasonality=seasonality, input_size=input_size, output_size=output_size,
                          frequency=frequency, max_periods=max_periods, random_seed=random_seed,
                          device=device, root_dir=root_dir)

        self.esrnn_ensemble = [deepcopy(esrnn).to(device)] * num_splits
        self.random_seed = random_seed

    def fit(self, X_df, y_df, X_test_df=None, y_test_df=None, shuffle=True):
        assert type(X_df) == pd.core.frame.DataFrame
        assert type(y_df) == pd.core.frame.DataFrame
        assert all([(col in X_df) for col in ['unique_id', 'ds', 'x']])
        assert all([(col in y_df) for col in ['unique_id', 'ds', 'y']])

        self.unique_ids = X_df['unique_id'].unique()
        self.num_series = len(self.unique_ids)
        chunk_size = np.ceil(self.num_series/self.num_splits)

        #random.seed(self.random_seed)
        #random.shuffle(self.unique_ids)

        # Create list with splits
        for i in range(self.num_splits):
            print('Training ESRNN ', i)
            ids_split = self.unique_ids[int(i*chunk_size):int((i+1)*chunk_size)]
            X_df_chunk = X_df[X_df['unique_id'].isin(ids_split)].reset_index(drop=True)
            y_df_chunk = y_df[y_df['unique_id'].isin(ids_split)].reset_index(drop=True)
            X_test_df_chunk = X_test_df[X_test_df['unique_id'].isin(ids_split)].reset_index(drop=True)
            y_test_df_chunk = y_test_df[y_test_df['unique_id'].isin(ids_split)].reset_index(drop=True)
            self.esrnn_ensemble[i].esrnn.to(self.device)
            self.esrnn_ensemble[i].fit(X_df_chunk, y_df_chunk, X_test_df_chunk, y_test_df_chunk)

        self._fitted = True

    def evaluate_model_prediction(self, y_train_df, X_test_df, y_test_df, epoch=None):
        assert self._fitted, "Model not fitted yet"

        self.owa = 0
        self.mase = 0
        self.smape = 0
        chunk_size = np.ceil(self.num_series/self.num_splits)
        for i in range(self.num_splits):
            ids_split = self.unique_ids[int(i*chunk_size):int((i+1)*chunk_size)]
            y_train_df_chunk = y_train_df[y_train_df['unique_id'].isin(ids_split)].reset_index(drop=True)
            X_test_df_chunk = X_test_df[X_test_df['unique_id'].isin(ids_split)].reset_index(drop=True)
            y_test_df_chunk = y_test_df[y_test_df['unique_id'].isin(ids_split)].reset_index(drop=True)
            owa_i, mase_i, smape_i = self.esrnn_ensemble[i].evaluate_model_prediction(y_train_df_chunk, X_test_df_chunk, y_test_df_chunk)
            self.owa += owa_i
            self.mase += mase_i
            self.smape += smape_i

        self.owa /= self.num_splits
        self.mase /= self.num_splits
        self.smape /= self.num_splits

        return self.owa, self.mase, self.smape