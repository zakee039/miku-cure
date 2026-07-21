import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models


class EmotionCNN(nn.Module):
    def __init__(self, num_classes=8):
        super(EmotionCNN, self).__init__()
        self.conv1_1 = nn.Conv2d(1, 32, kernel_size=3, padding=1)
        self.conv1_2 = nn.Conv2d(32, 64, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm2d(64)
        self.pool1 = nn.MaxPool2d(2, 2)
        self.drop1 = nn.Dropout(0.25)

        self.conv2 = nn.Conv2d(64, 128, kernel_size=5, padding=2)
        self.bn2 = nn.BatchNorm2d(128)
        self.pool2 = nn.MaxPool2d(2, 2)
        self.drop2 = nn.Dropout(0.25)

        self.conv3 = nn.Conv2d(128, 512, kernel_size=3, padding=1)
        self.bn3 = nn.BatchNorm2d(512)
        self.pool3 = nn.MaxPool2d(2, 2)
        self.drop3 = nn.Dropout(0.25)

        self.conv4 = nn.Conv2d(512, 512, kernel_size=3, padding=1)
        self.bn4 = nn.BatchNorm2d(512)
        self.pool4 = nn.MaxPool2d(2, 2)
        self.drop4 = nn.Dropout(0.25)

        self.conv5 = nn.Conv2d(512, 512, kernel_size=3, padding=1)
        self.bn5 = nn.BatchNorm2d(512)
        self.pool5 = nn.MaxPool2d(2, 2)
        self.drop5 = nn.Dropout(0.25)

        self.fc1 = nn.Linear(512 * 1 * 1, 256)
        self.bn_fc1 = nn.BatchNorm1d(256)
        self.drop_fc1 = nn.Dropout(0.25)

        self.fc2 = nn.Linear(256, 512)
        self.bn_fc2 = nn.BatchNorm1d(512)
        self.drop_fc2 = nn.Dropout(0.25)

        self.out = nn.Linear(512, num_classes)

    def forward(self, x):
        x = F.relu(self.conv1_1(x))
        x = F.relu(self.conv1_2(x))
        x = self.bn1(x)
        x = self.pool1(x)
        x = self.drop1(x)

        x = F.relu(self.conv2(x))
        x = self.bn2(x)
        x = self.pool2(x)
        x = self.drop2(x)

        x = F.relu(self.conv3(x))
        x = self.bn3(x)
        x = self.pool3(x)
        x = self.drop3(x)

        x = F.relu(self.conv4(x))
        x = self.bn4(x)
        x = self.pool4(x)
        x = self.drop4(x)

        x = F.relu(self.conv5(x))
        x = self.bn5(x)
        x = self.pool5(x)
        x = self.drop5(x)

        x = x.view(x.size(0), -1)

        x = F.relu(self.fc1(x))
        x = self.bn_fc1(x)
        x = self.drop_fc1(x)

        x = F.relu(self.fc2(x))
        x = self.bn_fc2(x)
        x = self.drop_fc2(x)

        x = self.out(x)
        return x


class GrayscaleMobileNetV2(nn.Module):
    """
    pretrained=True  : load ImageNet weights (training / transfer learning)
    pretrained=False : random init — use for inference when loading fine-tuned .pth
    """
    def __init__(self, num_classes=8, pretrained=False):
        super(GrayscaleMobileNetV2, self).__init__()
        weights = models.MobileNet_V2_Weights.DEFAULT if pretrained else None
        self.mobilenet = models.mobilenet_v2(weights=weights)

        original_conv = self.mobilenet.features[0][0]
        new_conv = nn.Conv2d(
            1, original_conv.out_channels,
            kernel_size=original_conv.kernel_size,
            stride=original_conv.stride,
            padding=original_conv.padding,
            bias=False,
        )
        if pretrained:
            with torch.no_grad():
                new_conv.weight.copy_(original_conv.weight.sum(dim=1, keepdim=True))

        self.mobilenet.features[0][0] = new_conv
        self.mobilenet.classifier[0] = nn.Dropout(p=0.5)
        self.mobilenet.classifier[1] = nn.Linear(self.mobilenet.last_channel, num_classes)

    def forward(self, x):
        return self.mobilenet(x)


class RNNAttentionNetwork(nn.Module):
    def __init__(self, num_classes=8):
        super(RNNAttentionNetwork, self).__init__()
        self.conv1_1 = nn.Conv2d(1, 32, kernel_size=3, padding=1)
        self.conv1_2 = nn.Conv2d(32, 64, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm2d(64)
        self.pool1 = nn.MaxPool2d(2, 2)
        self.drop1 = nn.Dropout(0.25)

        self.conv2 = nn.Conv2d(64, 128, kernel_size=5, padding=2)
        self.bn2 = nn.BatchNorm2d(128)
        self.pool2 = nn.MaxPool2d(2, 2)
        self.drop2 = nn.Dropout(0.25)

        self.feature_dim = 128
        self.seq_len = 12 * 12

        self.lstm = nn.LSTM(
            input_size=self.feature_dim, hidden_size=256,
            num_layers=2, batch_first=True, bidirectional=True, dropout=0.3,
        )

        self.mha = nn.MultiheadAttention(
            embed_dim=256 * 2, num_heads=8, batch_first=True, dropout=0.3,
        )

        self.classifier = nn.Sequential(
            nn.Linear(256 * 2, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(),
            nn.Dropout(0.4),
            nn.Linear(512, num_classes),
        )

    def forward(self, x):
        x = F.relu(self.conv1_1(x))
        x = F.relu(self.conv1_2(x))
        x = self.bn1(x)
        x = self.pool1(x)
        x = self.drop1(x)

        x = F.relu(self.conv2(x))
        x = self.bn2(x)
        x = self.pool2(x)
        x = self.drop2(x)

        b, c, h, w = x.size()
        x = x.view(b, c, h * w).permute(0, 2, 1)

        lstm_out, _ = self.lstm(x)
        attn_out, _ = self.mha(lstm_out, lstm_out, lstm_out)
        context_vector = torch.mean(attn_out, dim=1)
        out = self.classifier(context_vector)
        return out
