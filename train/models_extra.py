import torch
import torch.nn as nn
import torch.nn.functional as F

class RNNAttentionNetwork(nn.Module):
    def __init__(self, num_classes=8):
        super(RNNAttentionNetwork, self).__init__()
        # Block 1 (Match EmotionCNN)
        self.conv1_1 = nn.Conv2d(1, 32, kernel_size=3, padding=1)
        self.conv1_2 = nn.Conv2d(32, 64, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm2d(64)
        self.pool1 = nn.MaxPool2d(2, 2) # 24x24
        self.drop1 = nn.Dropout(0.25)
        
        # Block 2 (Match EmotionCNN, 5x5 kernel)
        self.conv2 = nn.Conv2d(64, 128, kernel_size=5, padding=2)
        self.bn2 = nn.BatchNorm2d(128)
        self.pool2 = nn.MaxPool2d(2, 2) # 12x12
        self.drop2 = nn.Dropout(0.25)
        
        self.feature_dim = 128
        self.seq_len = 12 * 12 # 144
        
        # Deep Bi-LSTM
        self.lstm = nn.LSTM(input_size=self.feature_dim, hidden_size=256, 
                            num_layers=2, batch_first=True, bidirectional=True, dropout=0.3)
        
        # Multi-Head Attention Mechanism
        self.mha = nn.MultiheadAttention(embed_dim=256 * 2, num_heads=8, batch_first=True, dropout=0.3)
        
        # Classifier
        self.classifier = nn.Sequential(
            nn.Linear(256 * 2, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(),
            nn.Dropout(0.4),
            nn.Linear(512, num_classes)
        )

    def forward(self, x):
        # CNN backbone Block 1
        x = F.relu(self.conv1_1(x))
        x = F.relu(self.conv1_2(x))
        x = self.bn1(x)
        x = self.pool1(x)
        x = self.drop1(x)
        
        # CNN backbone Block 2
        x = F.relu(self.conv2(x))
        x = self.bn2(x)
        x = self.pool2(x)
        x = self.drop2(x)
        
        # Reshape to sequence: (Batch, Channels, H, W) -> (Batch, H*W, Channels)
        b, c, h, w = x.size()
        x = x.view(b, c, h * w).permute(0, 2, 1) # (Batch, 144, 128)
        
        # RNN encoding
        lstm_out, _ = self.lstm(x) # lstm_out: (Batch, 144, 512)
        
        # Self-Attention weighting
        attn_out, _ = self.mha(lstm_out, lstm_out, lstm_out) # (Batch, 144, 512)
        
        # Context Vector: Global Average Pooling over the sequence
        context_vector = torch.mean(attn_out, dim=1) # (Batch, 512)
        
        # Classification
        out = self.classifier(context_vector)
        return out
