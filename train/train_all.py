import os
import sys
import argparse
import subprocess

def run_script(script_name, args_list):
    print(f"\n{'='*50}")
    print(f"Starting {script_name}")
    print(f"{'='*50}\n")
    
    script_path = os.path.join(os.path.dirname(__file__), script_name)
    command = [sys.executable, "-u", script_path] + args_list
    
    # Run the subprocess, letting it print directly to stdout/stderr
    process = subprocess.Popen(command, stdout=sys.stdout, stderr=sys.stderr)
    process.wait()
    
    if process.returncode != 0:
        print(f"\n[!] Error: {script_name} exited with code {process.returncode}")
        sys.exit(process.returncode)
    else:
        print(f"\n[*] Successfully completed {script_name}\n")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Train All Models Sequentially")
    parser.add_argument('--dataset', type=str, required=True, help="Path to dataset CSV")
    parser.add_argument('--lr', type=float, default=0.0001, help="Learning rate")
    parser.add_argument("--dynamic_lr", action="store_true", help="Enable dynamic learning rate")
    parser.add_argument('--epochs', type=int, default=30, help="Number of epochs")
    parser.add_argument('--batch_size', type=int, default=64, help="Batch size")
    parser.add_argument('--save_dir', type=str, default=os.path.join(os.path.dirname(__file__), "models"), help="Directory to save the best models")
    
    # Parse arguments just to ensure they are valid, but we will reconstruct the args list to pass down
    args = parser.parse_args()
    
    # Reconstruct the arguments for the child scripts
    child_args = [
        "--dataset", args.dataset,
        "--lr", str(args.lr),
        "--epochs", str(args.epochs),
        "--batch_size", str(args.batch_size),
        "--save_dir", args.save_dir
    ]
    if args.dynamic_lr:
        child_args.append("--dynamic_lr")
        
    print(f"Coordinator: Training All Models")
    print(f"Global Settings: Dataset={args.dataset}, Epochs={args.epochs}, BatchSize={args.batch_size}, LR={args.lr}, DynamicLR={args.dynamic_lr}")
    print(f"Save Directory: {args.save_dir}")

    # 1. Train CNN
    run_script("train_cnn.py", child_args)
    
    # 2. Train RNN
    run_script("train_rnn.py", child_args)
    
    # 3. Train MobileNet
    run_script("train_mobilenet.py", child_args)
    
    print(f"\n{'='*50}")
    print("All models trained successfully!")
    print(f"{'='*50}")
