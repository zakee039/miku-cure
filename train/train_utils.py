"""Shared training helpers: device, AMP, early stopping, DataLoader defaults."""
import os
import time

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader
except ImportError:
    torch = None


def get_device():
    if torch is None:
        return None
    if torch.cuda.is_available():
        try:
            t = torch.zeros(1, device='cuda') + 1
            del t
            return torch.device('cuda')
        except Exception as e:
            print(f"CUDA test failed: {e}. Falling back to CPU.")
    return torch.device('cpu')


def make_loaders(train_dataset, val_dataset, test_dataset, batch_size):
    device = get_device()
    use_cuda = device is not None and device.type == 'cuda'
    # Windows-friendly workers
    workers = min(4, os.cpu_count() or 1) if use_cuda else 0
    kw = dict(
        batch_size=batch_size,
        num_workers=workers,
        pin_memory=use_cuda,
        persistent_workers=workers > 0,
    )
    train_loader = DataLoader(train_dataset, shuffle=True, **kw)
    val_loader = DataLoader(val_dataset, shuffle=False, **kw)
    test_loader = DataLoader(test_dataset, shuffle=False, **kw)
    return train_loader, val_loader, test_loader


def train_pytorch_model(
    model,
    train_loader,
    val_loader,
    epochs=10,
    lr=0.0001,
    model_save_path="best_model.pth",
    dynamic_lr=False,
    early_stop_patience=5,
    weight_decay=1e-4,
    use_amp=True,
):
    device = get_device()
    model = model.to(device)
    print(f"Training on device: {device}")

    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = (
        optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.5, patience=2)
        if dynamic_lr else None
    )

    amp_enabled = bool(use_amp and device.type == 'cuda')
    # Prefer torch.amp API (PyTorch 2.x); fall back for older builds
    if torch and amp_enabled:
        try:
            scaler = torch.amp.GradScaler('cuda', enabled=True)
            _autocast = lambda: torch.amp.autocast('cuda')
        except Exception:
            scaler = torch.cuda.amp.GradScaler(enabled=True)
            _autocast = torch.cuda.amp.autocast
    else:
        scaler = None
        _autocast = None

    best_acc = 0.0
    epochs_no_improve = 0

    for epoch in range(epochs):
        model.train()
        running_loss = 0.0
        correct = 0
        total = 0
        start_time = time.time()

        for images, labels in train_loader:
            images, labels = images.to(device, non_blocking=True), labels.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            if amp_enabled and scaler is not None:
                with _autocast():
                    outputs = model(images)
                    loss = criterion(outputs, labels)
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
            else:
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
                images, labels = images.to(device, non_blocking=True), labels.to(device, non_blocking=True)
                if amp_enabled and _autocast is not None:
                    with _autocast():
                        outputs = model(images)
                        loss = criterion(outputs, labels)
                else:
                    outputs = model(images)
                    loss = criterion(outputs, labels)
                val_loss += loss.item() * images.size(0)
                _, predicted = torch.max(outputs, 1)
                val_total += labels.size(0)
                val_correct += (predicted == labels).sum().item()

        val_epoch_loss = val_loss / len(val_loader.dataset)
        val_epoch_acc = val_correct / val_total
        elapsed = time.time() - start_time
        print(
            f"Epoch {epoch+1}/{epochs} ({elapsed:.1f}s) - "
            f"Loss: {epoch_loss:.4f}, Acc: {epoch_acc*100:.2f}% | "
            f"Val Loss: {val_epoch_loss:.4f}, Val Acc: {val_epoch_acc*100:.2f}%"
        )

        if scheduler is not None:
            scheduler.step(val_epoch_acc)

        if val_epoch_acc > best_acc:
            best_acc = val_epoch_acc
            epochs_no_improve = 0
            os.makedirs(os.path.dirname(model_save_path) or '.', exist_ok=True)
            torch.save(model.state_dict(), model_save_path)
            print(f"Saved new best model with Val Acc: {best_acc*100:.2f}%")
        else:
            epochs_no_improve += 1
            if early_stop_patience and epochs_no_improve >= early_stop_patience:
                print(
                    f"Early stopping at epoch {epoch+1} "
                    f"(no val improvement for {early_stop_patience} epochs)."
                )
                break

    print(f"Training completed. Best Validation Accuracy: {best_acc*100:.2f}%")
    return model


def evaluate_pytorch_model(model, test_loader, model_path):
    from sklearn.metrics import classification_report, confusion_matrix

    device = get_device()
    model = model.to(device)
    try:
        state = torch.load(model_path, map_location=device, weights_only=True)
    except TypeError:
        state = torch.load(model_path, map_location=device)
    model.load_state_dict(state)
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
