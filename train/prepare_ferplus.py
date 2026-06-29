import pandas as pd
import numpy as np
import os

def prepare_ferplus():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    fer_path = os.path.join(base_dir, 'datasets', 'fer2013.csv')
    ferplus_path = os.path.join(base_dir, '..', '开发', 'FERPlus-master', 'fer2013new.csv')
    out_path = os.path.join(base_dir, 'datasets', 'fer2013_plus.csv')
    
    print(f"Loading {fer_path}...")
    fer_df = pd.read_csv(fer_path)
    print(f"Loading {ferplus_path}...")
    ferplus_df = pd.read_csv(ferplus_path)
    
    if len(fer_df) != len(ferplus_df):
        print("ERROR: Row count mismatch!")
        return
        
    emotions = ['neutral', 'happiness', 'surprise', 'sadness', 'anger', 'disgust', 'fear', 'contempt', 'unknown', 'NF']
    
    new_rows = []
    
    for i in range(len(ferplus_df)):
        votes = ferplus_df.iloc[i, 2:].values.astype(int)
        
        # Check if max vote is unique
        max_vote = np.max(votes)
        max_indices = np.where(votes == max_vote)[0]
        
        # If tied, or if max vote goes to 'unknown' (8) or 'NF' (9), skip this image
        if len(max_indices) > 1 or max_indices[0] >= 8:
            continue
            
        # Valid emotion found
        emotion_idx = max_indices[0]
        
        # Original usage and pixels
        pixels = fer_df.iloc[i]['pixels']
        usage = ferplus_df.iloc[i]['Usage']
        
        new_rows.append({
            'emotion': emotion_idx,
            'pixels': pixels,
            'Usage': usage
        })
        
    plus_df = pd.DataFrame(new_rows)
    print(f"Saving to {out_path}...")
    plus_df.to_csv(out_path, index=False)
    print(f"Done! Processed {len(plus_df)} valid images out of {len(fer_df)}.")

if __name__ == '__main__':
    prepare_ferplus()
