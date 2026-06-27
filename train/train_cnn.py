import argparse
import os
import sys
import pandas as pd
import numpy as np
import time

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import Dataset, DataLoader
    import torchvision.transforms as transforms
except ImportError:
    torch = None

try:
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report, confusion_matrix
except ImportError:
    pass

# Import the EmotionCNN from our detector
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))
try:
    from detector import EmotionCNN
except ImportError:
    EmotionCNN = None

class FER2013Dataset(Dataset):
    def __init__(self, df, transform=None):
        self.transform = transform
        self.labels = df['emotion'].values
        pixels_list = df['pixels'].tolist()
        self.images = np.array([np.fromstring(pixel_str, dtype=np.uint8, sep=' ').reshape(48, 48) for pixel_str in pixels_list])

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

def get_device():
    if torch.cuda.is_available():
        try:
            test_device = torch.device('cuda')
            test_tensor = torch.zeros(1, device=test_device) + 1
            return test_device
        except Exception as e:
            print(f"CUDA test failed: {e}. Falling back to CPU.")
    return torch.device('cpu')

def train_pytorch_model(model, train_loader, val_loader, epochs=10, lr=0.0001, model_save_path="best_model.pth", dynamic_lr=False):
    device = get_device()
    model = model.to(device)
    print(f"Training on device: {device}")
    
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.5, patience=2) if dynamic_lr else None
    
    best_score = -float('inf')
    best_acc = 0.0
    for epoch in range(epochs):
        model.train()
        running_loss = 0.0
        correct = 0
        total = 0
        start_time = time.time()
        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item() * images.size(0)
            _, predicted = torch.max(outputs, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
            
        epoch_loss = running_loss / len(train_loader.dataset)
        epoch_acc = correct / total
        
        model.eval()
        val_loss = 0.0
        val_correct = 0
        val_total = 0
        with torch.no_grad():
            for images, labels in val_loader:
                images, labels = images.to(device), labels.to(device)
                outputs = model(images)
                loss = criterion(outputs, labels)
                val_loss += loss.item() * images.size(0)
                _, predicted = torch.max(outputs, 1)
                val_total += labels.size(0)
                val_correct += (predicted == labels).sum().item()
                
        val_epoch_loss = val_loss / len(val_loader.dataset)
        val_epoch_acc = val_correct / val_total
        elapsed = time.time() - start_time
        print(f"Epoch {epoch+1}/{epochs} ({elapsed:.1f}s) - "
              f"Loss: {epoch_loss:.4f}, Acc: {epoch_acc*100:.2f}% | "
              f"Val Loss: {val_epoch_loss:.4f}, Val Acc: {val_epoch_acc*100:.2f}%")
              
        if scheduler is not None:
            scheduler.step(val_epoch_acc)
            
        gap = max(0.0, epoch_acc - val_epoch_acc)
        score = val_epoch_acc - 4.0 * gap
        
        gen_path = model_save_path.replace('.pth', '_gen.pth')
        acc_path = model_save_path.replace('.pth', '_acc.pth')
        
        msg = []
        if score > best_score:
            best_score = score
            os.makedirs(os.path.dirname(gen_path), exist_ok=True)
            torch.save(model.state_dict(), gen_path)
            msg.append(f"Gen-Score: {score*100:.2f}")
            
        if val_epoch_acc > best_acc:
            best_acc = val_epoch_acc
            os.makedirs(os.path.dirname(acc_path), exist_ok=True)
            torch.save(model.state_dict(), acc_path)
            msg.append(f"Val-Acc: {best_acc*100:.2f}%")
            
        if msg:
            print(f"Saved new best model(s) -> {' | '.join(msg)}")
            
    print(f"Training completed. Best Gen-Score: {best_score*100:.2f} | Best Val-Acc: {best_acc*100:.2f}%")
    return model

def evaluate_pytorch_model(model, test_loader, model_path):
    device = get_device()
    model = model.to(device)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()
    all_preds = []
    all_labels = []
    with torch.no_grad():
        for images, labels in test_loader:
            images = images.to(device)
            outputs = model(images)
            _, predicted = torch.max(outputs, 1)
            all_preds.extend(predicted.cpu().numpy())
            all_labels.extend(labels.numpy())
            
    emotions = ['neutral', 'happy', 'surprise', 'sadness', 'anger', 'disgust', 'fear', 'contempt']
    print("\n--- Classification Report ---")
    print(classification_report(all_labels, all_preds, target_names=emotions, digits=3))
    print("--- Confusion Matrix ---")
    print(confusion_matrix(all_labels, all_preds))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Train EmotionCNN Model")
    parser.add_argument('--dataset', type=str, required=True, help="Path to dataset CSV")
    parser.add_argument("--lr", type=float, default=0.0001, help="Learning rate")
    parser.add_argument("--dynamic_lr", action="store_true", help="Enable dynamic learning rate")
    parser.add_argument('--epochs', type=int, default=30, help="Number of epochs")
    parser.add_argument('--batch_size', type=int, default=64, help="Batch size")
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
    
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size, shuffle=False)
    
    print("\n================== Training Custom CNN Model ==================")
    custom_model = EmotionCNN()
    os.makedirs(args.save_dir, exist_ok=True)
    cnn_save_path = os.path.join(args.save_dir, "best_cnn.pth")
    print(f"[*] Started training CNN for {args.epochs} epochs with initial LR {args.lr} (Dynamic: {args.dynamic_lr})...")
    train_pytorch_model(custom_model, train_loader, val_loader, epochs=args.epochs, lr=args.lr, model_save_path=cnn_save_path, dynamic_lr=args.dynamic_lr)
    print(f"[*] Training complete. Models saved with suffixes _gen.pth and _acc.pth")
    evaluate_pytorch_model(custom_model, test_loader, cnn_save_path.replace('.pth', '_gen.pth'))
