# -*- coding: utf-8 -*-
# @Time   : 2020/7/21 9:23
# @Author : Zihan Lin
# @Email  : linzihan.super@foxmail.com
# @File   : afm.py

"""
Reference:
"Attentional Factorization Machines: Learning the Weight of Feature Interactions via Attention Networks" in IJCAI 2017.
"""

import torch
import torch.nn.functional as F
import torch.nn as nn
from torch.nn.init import xavier_normal_, constant_

from ..layers import AttLayer
from .context_recommender import ContextRecommender


class AFM(ContextRecommender):

    def __init__(self, config, dataset):
        super(AFM, self).__init__(config, dataset)

        self.LABEL = config['LABEL_FIELD']

        self.attention_size = config['attention_size']
        self.dropout = config['dropout']
        self.weight_decay = config['weight_decay']
        self.num_pair = self.num_feature_field * (self.num_feature_field-1) / 2
        self.attlayer = AttLayer(self.embedding_size, self.attention_size)
        self.p = nn.Parameter(torch.randn(self.embedding_size), requires_grad=True)
        self.sigmoid = nn.Sigmoid()
        self.loss = nn.MSELoss()

        self.apply(self.init_weights)

    def init_weights(self, module):
        if isinstance(module, nn.Embedding):
            xavier_normal_(module.weight.data)
        elif isinstance(module, nn.Linear):
            xavier_normal_(module.weight.data)
            if module.bias is not None:
                constant_(module.bias.data, 0)

    def build_cross(self, feat_emb):
        # num_pairs = num_feature_field * (num_feature_field-1) / 2
        row = []
        col = []
        for i in range(self.num_feature_field - 1):
            for j in range(i + 1, self.num_feature_field):
                row.append(i)
                col.append(j)
        p = feat_emb[:, row]  # [batch_size, num_pairs, emb_dim]
        q = feat_emb[:, col]  # [batch_size, num_pairs, emb_dim]
        return p, q

    def afm_layer(self, infeature):
        """
        Input shape
        - A 3D tensor with shape:``(batch_size,field_size,embed_dim)``.

        Output shape
        - 3D tensor with shape: ``(batch_size,1)`` .
        """
        p, q = self.build_cross(infeature)
        pair_wise_inter = torch.mul(p, q)  # [batch_size, num_pairs, emb_dim]

        # [batch_size, num_pairs, 1]
        att_signal = F.dropout(self.attlayer(pair_wise_inter), self.dropout[0]).unsqueeze(dim=2)

        att_inter = torch.mul(att_signal, pair_wise_inter)  # [batch_size, num_pairs, emb_dim]
        att_pooling = torch.sum(att_inter, dim=1)  # [batch_size, emb_dim]
        att_pooling = F.dropout(att_pooling, self.dropout[1])  # [batch_size, emb_dim]

        att_pooling = torch.mul(att_pooling, self.p)  # [batch_size, emb_dim]
        att_pooling = torch.sum(att_pooling, dim=1, keepdim=True)  # [batch_size, 1]

        return att_pooling

    def forward(self, interaction):
        # sparse_embedding shape: [batch_size, num_token_seq_field+num_token_field, embed_dim] or None
        # dense_embedding shape: [batch_size, num_float_field] or [batch_size, num_float_field, embed_dim] or None
        sparse_embedding, dense_embedding = self.embed_input_fields(interaction)
        x = []
        if sparse_embedding is not None:
            x.append(sparse_embedding)
        if dense_embedding is not None and len(dense_embedding.shape) == 3:
            x.append(dense_embedding)
        x = torch.cat(x, dim=1)  # [batch_size, num_field, embed_dim]

        y = self.first_order_linear(interaction) + self.afm_layer(x)
        return y.squeeze()

    def calculate_loss(self, interaction):
        label = interaction[self.LABEL]

        output = self.forward(interaction)
        l2_loss = self.weight_decay * torch.norm(self.attlayer.w.weight, p=2)
        return torch.sqrt(self.loss(output, label)) + l2_loss

    def predict(self, interaction):
        return self.forward(interaction)