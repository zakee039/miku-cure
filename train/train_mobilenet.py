import argparse
import os
import sys
import pandas as pd
import numpy as np

try:
    import torch
    from torch.utils.data import Dataset
    import torchvision.transforms as transforms
except ImportError:
    torch = None

try:
    from sklearn.model_selection import train_test_split
except ImportError:
    train_test_split = None

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
sys.path.insert(0, os.path.dirname(__file__))

from models_def import GrayscaleMobileNetV2
from train_utils import train_pytorch_model, evaluate_pytorch_model, make_loaders


class FER2013Dataset(Dataset):
    def __init__(self, df, transform=None):
        self.transform = transform
        self.labels = df['emotion'].values
        pixels_list = df['pixels'].tolist()
        self.images = np.array([
            np.fromstring(pixel_str, dtype=np.uint8, sep=' ').reshape(48, 48)
            for pixel_str in pixels_list
        ])

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        image = self.images[idx]
        label = self.labels[idx]
        image = image.astype(np.float32) / 255.0
        if self.transform:
            image = self.transform(image)
        else:
            image = torch.tensor(image).unsqueeze(0)
        label = torch.tensor(label, dtype=torch.long)
        return image, label


def load_data(csv_path):
    print(f"Loading dataset from {csv_path}...")
    df = pd.read_csv(csv_path)
    print(f"Dataset shape: {df.shape}")
    if 'Usage' in df.columns:
        train_df = df[df['Usage'] == 'Training']
        val_df = df[df['Usage'] == 'PublicTest']
        test_df = df[df['Usage'] == 'PrivateTest']
    else:
        train_df, test_df = train_test_split(df, test_size=0.2, random_state=42)
        train_df, val_df = train_test_split(train_df, test_size=0.1, random_state=42)
    return train_df, val_df, test_df


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Train Fine-tuned MobileNetV2 Model")
    parser.add_argument('--dataset', type=str, required=True, help="Path to dataset CSV")
    parser.add_argument('--lr', type=float, default=0.0001, help="Learning rate")
    parser.add_argument("--dynamic_lr", action="store_true", help="Enable dynamic learning rate")
    parser.add_argument('--epochs', type=int, default=30, help="Number of epochs")
    parser.add_argument('--batch_size', type=int, default=64, help="Batch size")
    parser.add_argument('--early_stop', type=int, default=5, help="Early stop patience (0=off)")
    parser.add_argument('--save_dir', type=str, default=os.path.join(os.path.dirname(__file__), "models"), help="Directory to save the best model")
    args = parser.parse_args()

    if not os.path.exists(args.dataset):
        print(f"Dataset not found at {args.dataset}")
        sys.exit(1)

    train_df, val_df, test_df = load_data(args.dataset)
    print(f"Dataset sizes: Train={len(train_df)}, Val={len(val_df)}, Test={len(test_df)}")

    train_transform = transforms.Compose([
        transforms.ToPILImage(),
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(15),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.5], std=[0.5])
    ])

    val_transform = transforms.Compose([
        transforms.ToPILImage(),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.5], std=[0.5])
    ])

    train_dataset = FER2013Dataset(train_df, transform=train_transform)
    val_dataset = FER2013Dataset(val_df, transform=val_transform)
    test_dataset = FER2013Dataset(test_df, transform=val_transform)

    train_loader, val_loader, test_loader = make_loaders(
        train_dataset, val_dataset, test_dataset, args.batch_size
    )

    print("\n================== Training Fine-tuned MobileNetV2 ==================")
    # Training uses ImageNet-initialized backbone; inference loads pretrained=False + fine-tuned weights
    mobilenet_model = GrayscaleMobileNetV2(pretrained=True)
    print(f"[*] Started fine-tuning MobileNetV2 for {args.epochs} epochs with initial LR {args.lr} (Dynamic: {args.dynamic_lr})...")
    os.makedirs(args.save_dir, exist_ok=True)
    mobilenet_save_path = os.path.join(args.save_dir, "best_mobilenet_v2.pth")
    train_pytorch_model(
        mobilenet_model, train_loader, val_loader,
        epochs=args.epochs, lr=args.lr, model_save_path=mobilenet_save_path,
        dynamic_lr=args.dynamic_lr, weight_decay=5e-4, early_stop_patience=args.early_stop,
    )
    print(f"[*] Training complete. Best model saved to {mobilenet_save_path}")
    evaluate_pytorch_model(mobilenet_model, test_loader, mobilenet_save_path)
