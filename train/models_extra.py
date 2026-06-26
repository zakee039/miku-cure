import torch
import torch.nn as nn
import torch.nn.functional as F

class RNNAttentionNetwork(nn.Module):
    def __init__(self, num_classes=8):
        super(RNNAttentionNetwork, self).__init__()
        # Simple CNN backbone to get spatial features
        self.conv1 = nn.Conv2d(1, 32, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm2d(32)
        self.pool1 = nn.MaxPool2d(2, 2) # 24x24
        
        self.conv2 = nn.Conv2d(32, 64, kernel_size=3, padding=1)
        self.bn2 = nn.BatchNorm2d(64)
        self.pool2 = nn.MaxPool2d(2, 2) # 12x12
        
        self.feature_dim = 64
        self.seq_len = 12 * 12 # 144
        
        # Bi-LSTM
        self.lstm = nn.LSTM(input_size=self.feature_dim, hidden_size=128, 
                            num_layers=1, batch_first=True, bidirectional=True)
        
        # Attention Mechanism
        self.attention_fc = nn.Linear(128 * 2, 1)
        
        # Classifier
        self.classifier = nn.Sequential(
            nn.Linear(128 * 2, 256),
            nn.BatchNorm1d(256),
            nn.ReLU(),
            nn.Dropout(0.4),
            nn.Linear(256, num_classes)
        )

    def forward(self, x):
        # CNN backbone
        x = F.relu(self.bn1(self.conv1(x)))
        x = self.pool1(x)
        x = F.relu(self.bn2(self.conv2(x)))
        x = self.pool2(x)
        
        # Reshape to sequence: (Batch, Channels, H, W) -> (Batch, H*W, Channels)
        b, c, h, w = x.size()
        x = x.view(b, c, h * w).permute(0, 2, 1) # (Batch, 144, 64)
        
        # RNN encoding
        lstm_out, _ = self.lstm(x) # lstm_out: (Batch, 144, 256)
        
        # Attention weighting
        attention_weights = F.softmax(self.attention_fc(lstm_out), dim=1) # (Batch, 144, 1)
        context_vector = torch.sum(attention_weights * lstm_out, dim=1) # (Batch, 256)
        
        # Classification
        out = self.classifier(context_vector)
        return out
