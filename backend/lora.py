import torch
import torch.nn as nn
import math

class LoRALinear(nn.Module):
    def __init__(self, linear_layer: nn.Linear, r: int = 8, alpha: int = 16):
        super().__init__()
        self.in_features = linear_layer.in_features
        self.out_features = linear_layer.out_features
        self.r = r
        self.alpha = alpha
        
        # Store the original linear layer (frozen during training)
        self.linear = linear_layer
        
        # Add LoRA matrices A and B
        self.lora_A = nn.Parameter(torch.zeros((r, self.in_features)))
        self.lora_B = nn.Parameter(torch.zeros((self.out_features, r)))
        
        # Initialization
        nn.init.kaiming_uniform_(self.lora_A, a=math.sqrt(5))
        nn.init.zeros_(self.lora_B)

    def forward(self, x: torch.Tensor):
        # Y = WX + (alpha/r) * BAX
        orig_out = self.linear(x)
        lora_out = (x @ self.lora_A.T @ self.lora_B.T) * (self.alpha / self.r)
        return orig_out + lora_out

def inject_lora(model: nn.Module, r: int = 8, alpha: int = 16):
    """
    Injects LoRA into the final classification layer of the model.
    """
    from models_def import EmotionCNN, GrayscaleMobileNetV2, RNNAttentionNetwork
    
    if isinstance(model, EmotionCNN):
        if not isinstance(model.out, LoRALinear):
            model.out = LoRALinear(model.out, r=r, alpha=alpha)
    elif isinstance(model, GrayscaleMobileNetV2):
        if not isinstance(model.mobilenet.classifier[1], LoRALinear):
             model.mobilenet.classifier[1] = LoRALinear(model.mobilenet.classifier[1], r=r, alpha=alpha)
    elif isinstance(model, RNNAttentionNetwork):
        # classifier is a Sequential: Linear, BatchNorm, ReLU, Dropout, Linear
        if not isinstance(model.classifier[4], LoRALinear):
            model.classifier[4] = LoRALinear(model.classifier[4], r=r, alpha=alpha)
            
    return model
