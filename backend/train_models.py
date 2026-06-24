import os
import sys
import pandas as pd
import numpy as np
import pickle
import time

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import Dataset, DataLoader
    import torchvision.transforms as transforms
    import torchvision.models as models
except ImportError:
    torch = None

try:
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.svm import LinearSVC
    from sklearn.preprocessing import StandardScaler
except ImportError:
    pass

# Import the EmotionCNN from our detector
sys.path.append(os.path.dirname(__file__))
from detector import EmotionCNN

class FER2013Dataset(Dataset):
    def __init__(self, df, transform=None):
        self.transform = transform
        self.labels = df['emotion'].values
        
        # Parse pixel strings to numpy arrays
        pixels_list = df['pixels'].tolist()
        self.images = np.array([np.fromstring(pixel_str, dtype=np.uint8, sep=' ').reshape(48, 48) for pixel_str in pixels_list])

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        image = self.images[idx]
        label = self.labels[idx]
        
        # Convert to float and normalize to [0, 1]
        image = image.astype(np.float32) / 255.0
        
        if self.transform:
            # Transforms usually expect PIL images or float tensors
            image = self.transform(image)
        else:
            image = torch.tensor(image).unsqueeze(0) # (1, 48, 48)
            
        label = torch.tensor(label, dtype=torch.long)
        return image, label

def load_data(csv_path):
    print(f"Loading dataset from {csv_path}...")
    df = pd.read_csv(csv_path)
    print(f"Dataset shape: {df.shape}")
    
    # Split by Usage column if available (standard FER2013 has this)
    if 'Usage' in df.columns:
        train_df = df[df['Usage'] == 'Training']
        val_df = df[df['Usage'] == 'PublicTest']
        test_df = df[df['Usage'] == 'PrivateTest']
        print(f"Split sizes: Train={len(train_df)}, Val={len(val_df)}, Test={len(test_df)}")
    else:
        # Fallback random split
        train_df, test_df = train_test_split(df, test_size=0.2, random_state=42)
        train_df, val_df = train_test_split(train_df, test_size=0.1, random_state=42)
        print(f"Random split sizes: Train={len(train_df)}, Val={len(val_df)}, Test={len(test_df)}")
        
    return train_df, val_df, test_df

# Helper to train a PyTorch model
def train_pytorch_model(model, train_loader, val_loader, epochs=10, model_save_path="best_model.pth"):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = model.to(device)
    print(f"Training on device: {device}")
    
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.0001, weight_decay=1e-4)
    
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
        
        # Validation pass
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
              
        if val_epoch_acc > best_acc:
            best_acc = val_epoch_acc
            os.makedirs(os.path.dirname(model_save_path), exist_ok=True)
            torch.save(model.state_dict(), model_save_path)
            print(f"Saved new best model with Val Acc: {best_acc*100:.2f}%")
            
    print(f"Training completed. Best Validation Accuracy: {best_acc*100:.2f}%")
    return model

def evaluate_pytorch_model(model, test_loader, model_path):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
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
            
    emotions = ['anger', 'disgust', 'fear', 'happy', 'sadness', 'surprise', 'neutral']
    print("\n--- Classification Report ---")
    print(classification_report(all_labels, all_preds, target_names=emotions, digits=3))
    
    print("--- Confusion Matrix ---")
    print(confusion_matrix(all_labels, all_preds))

# HOG/Flat Pixel + SVM training helper
def train_svm(train_df, test_df, model_save_path):
    print("\n--- Training SVM Baseline (using Flat Pixels for speed) ---")
    
    X_train = np.array([np.fromstring(p, dtype=np.uint8, sep=' ') for p in train_df['pixels']])
    y_train = train_df['emotion'].values
    
    X_test = np.array([np.fromstring(p, dtype=np.uint8, sep=' ') for p in test_df['pixels']])
    y_test = test_df['emotion'].values
    
    # Scale pixels to speed up linear SVM convergence
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Train SVM
    print("Fitting LinearSVC...")
    clf = LinearSVC(max_iter=1000, random_state=42, verbose=1)
    start_time = time.time()
    clf.fit(X_train_scaled, y_train)
    print(f"SVM training completed in {time.time() - start_time:.1f}s")
    
    # Save SVM model
    os.makedirs(os.path.dirname(model_save_path), exist_ok=True)
    with open(model_save_path, 'wb') as f:
        pickle.dump((scaler, clf), f)
    print(f"Saved SVM model to {model_save_path}")
    
    # Evaluate
    y_pred = clf.predict(X_test_scaled)
    emotions = ['anger', 'disgust', 'fear', 'happy', 'sadness', 'surprise', 'neutral']
    print("\n--- SVM Classification Report ---")
    print(classification_report(y_test, y_pred, target_names=emotions, digits=3))

# MobileNetV2 definition for 1-channel Grayscale inputs
class GrayscaleMobileNetV2(nn.Module):
    def __init__(self, num_classes=7):
        super(GrayscaleMobileNetV2, self).__init__()
        self.mobilenet = models.mobilenet_v2(pretrained=True)
        
        # Modify the first conv layer to accept 1 channel instead of 3
        # Duplicate weights of original first layer across 1 input channel
        original_conv = self.mobilenet.features[0][0]
        new_conv = nn.Conv2d(1, original_conv.out_channels, 
                             kernel_size=original_conv.kernel_size, 
                             stride=original_conv.stride, 
                             padding=original_conv.padding, 
                             bias=False)
        with torch.no_grad():
            new_conv.weight.copy_(original_conv.weight.sum(dim=1, keepdim=True))
        
        self.mobilenet.features[0][0] = new_conv
        
        # Modify classifier to output 7 classes
        self.mobilenet.classifier[1] = nn.Linear(self.mobilenet.last_channel, num_classes)

    def forward(self, x):
        return self.mobilenet(x)

if __name__ == '__main__':
    csv_path = r"f:\project\期末大作业\datasets\fer2013.csv"
    if not os.path.exists(csv_path):
        print(f"Dataset not found at {csv_path}. Please place fer2013.csv there.")
        sys.exit(1)
        
    train_df, val_df, test_df = load_data(csv_path)
    
    # Subset data for fast CPU execution (10% of dataset)
    train_df = train_df.sample(frac=0.1, random_state=42).reset_index(drop=True)
    val_df = val_df.sample(frac=0.1, random_state=42).reset_index(drop=True)
    test_df = test_df.sample(frac=0.1, random_state=42).reset_index(drop=True)
    print(f"Subset sizes for fast CPU training: Train={len(train_df)}, Val={len(val_df)}, Test={len(test_df)}")
    
    # Set up transforms
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
    
    # Datasets & Loaders
    train_dataset = FER2013Dataset(train_df, transform=train_transform)
    val_dataset = FER2013Dataset(val_df, transform=val_transform)
    test_dataset = FER2013Dataset(test_df, transform=val_transform)
    
    train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=64, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=64, shuffle=False)
    
    # 1. Train Custom CNN
    print("\n================== 1. Training Custom CNN Model ==================")
    custom_model = EmotionCNN()
    cnn_save_path = os.path.join(os.path.dirname(__file__), "models", "best_cnn.pth")
    # Quick 3 epochs for fast CPU training demo
    train_pytorch_model(custom_model, train_loader, val_loader, epochs=3, model_save_path=cnn_save_path)
    evaluate_pytorch_model(custom_model, test_loader, cnn_save_path)
    
    # 2. Train SVM Baseline
    print("\n================== 2. Training SVM Baseline Model ==================")
    svm_save_path = os.path.join(os.path.dirname(__file__), "models", "svm_model.pkl")
    train_svm(train_df, test_df, svm_save_path)
    
    # 3. Train Fine-tuned MobileNetV2
    print("\n================== 3. Training Fine-tuned MobileNetV2 ==================")
    mobilenet_model = GrayscaleMobileNetV2()
    mobilenet_save_path = os.path.join(os.path.dirname(__file__), "models", "best_mobilenet.pth")
    train_pytorch_model(mobilenet_model, train_loader, val_loader, epochs=3, model_save_path=mobilenet_save_path)
    evaluate_pytorch_model(mobilenet_model, test_loader, mobilenet_save_path)
