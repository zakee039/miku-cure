import time
import os
import sys
import threading
from dotenv import load_dotenv

# Add backend directory to path to support running directly
sys.path.append(os.path.dirname(__file__))

from camera import Camera
from detector import EmotionDetector
from logger import EmotionLogger
from llm import MikuLLM
from websocket_server import MikuWebSocketServer

# Global State Variables
is_running = True
focus_active = False
focus_duration_mins = 30
focus_start_time = 0

# Negative emotion trigger tracking
negative_emotions_set = {'sadness', 'anger', 'fear', 'disgust'}
current_negative_emotion = None
negative_emotion_start_time = None
bubble_triggered = False

# Instantiate components
camera = Camera(device_index=0, target_fps=1)
detector = EmotionDetector(model_type='cnn')
logger = EmotionLogger()
llm = MikuLLM()
ws_server = MikuWebSocketServer()

def handle_frontend_message(data):
    """
    Callback to handle incoming JSON commands from Electron frontend.
    """
    global focus_active, focus_duration_mins, focus_start_time
    global current_negative_emotion, negative_emotion_start_time, bubble_triggered
    
    msg_type = data.get('type')
    
    if msg_type == 'start_focus':
        focus_duration_mins = data.get('duration_minutes', 30)
        focus_active = True
        focus_start_time = time.time()
        
        # Reset negative emotion tracking
        current_negative_emotion = None
        negative_emotion_start_time = None
        bubble_triggered = False
        
        logger.start_session(duration_minutes=focus_duration_mins)
        print(f"Backend: Focus started for {focus_duration_mins} minutes.")
        
    elif msg_type == 'end_focus':
        if not focus_active:
            return
            
        completed = data.get('completed', True)
        focus_active = False
        
        # 1. Get temporary stats to feed to LLM
        emotion_durations = {}
        for entry in logger.current_session_entries:
            emotion_durations[entry.emotion] = emotion_durations.get(entry.emotion, 0) + entry.duration
            
        total_seconds = sum(emotion_durations.values()) or 1
        stats = {em: (emotion_durations.get(em, 0) / total_seconds) * 100 for em in detector.EMOTIONS}
        
        # 2. Get LLM response
        comment = llm.get_focus_end_response(focus_duration_mins, stats)
        
        # 3. Finalize log entry in markdown
        final_stats = logger.end_session(completed=completed, miku_comment=comment)
        
        # 4. Push report back to Electron frontend
        ws_server.send_to_all({
            "type": "focus_report",
            "duration_minutes": focus_duration_mins,
            "stats": final_stats,
            "comment": comment,
            "completed": completed
        })
        print("Backend: Focus ended. Report sent to frontend.")
        
    elif msg_type == 'bubble_dismissed':
        # User dismissed the Miku care bubble, allow triggers to happen again
        # after emotion resets or when the timer is reset
        bubble_triggered = False
        current_negative_emotion = None
        negative_emotion_start_time = None
        print("Backend: Care bubble dismissed by user.")

    elif msg_type == 'change_model':
        model_type = data.get('model_type', 'cnn')
        detector.switch_model(model_type)

    elif msg_type == 'toggle_camera':
        state = data.get('state', True)
        if state:
            camera.start()
            print("Backend: Camera started by user.")
        else:
            camera.stop()
            print("Backend: Camera stopped by user.")

def main_loop():
    global is_running, focus_active
    global current_negative_emotion, negative_emotion_start_time, bubble_triggered
    
    print("Backend: Main detection loop running.")
    while is_running:
        start_time = time.time()
        
        # 1. Grab camera frame
        frame = camera.get_frame()
        if frame is not None:
            # 2. Detect emotion
            emotion, confidence, bbox = detector.detect_emotion(frame)
            
            # Pack bbox to json-friendly list [x, y, w, h]
            bbox_list = list(bbox) if bbox else None
            
            # 3. Broadcast real-time update
            ws_server.send_to_all({
                "type": "emotion_update",
                "emotion": emotion,
                "confidence": confidence,
                "bbox": bbox_list
            })
            
            # 4. Handle logging and negative triggers if focus is active
            if focus_active:
                logger.log_emotion(emotion, confidence)
                
                # Check negative emotion rule (>60s)
                if emotion in negative_emotions_set:
                    if current_negative_emotion != emotion:
                        current_negative_emotion = emotion
                        negative_emotion_start_time = time.time()
                    else:
                        elapsed = time.time() - negative_emotion_start_time
                        # If negative emotion has persisted for over 60s and we haven't triggered a bubble yet
                        if elapsed >= 60.0 and not bubble_triggered:
                            print(f"Backend: Triggered negative emotion care bubble for {emotion} ({elapsed:.1f}s)")
                            # Generate comforting comment from LLM
                            comment = llm.get_unhappy_response(emotion, duration_seconds=int(elapsed))
                            # Send bubble request to frontend
                            ws_server.send_to_all({
                                "type": "trigger_bubble",
                                "text": comment,
                                "show_actions": True
                            })
                            bubble_triggered = True
                else:
                    # Reset negative emotion timers when they recover (happy, neutral, surprise)
                    current_negative_emotion = None
                    negative_emotion_start_time = None
                    # Wait for recovery before triggering care bubble again
                    bubble_triggered = False
        
        # Sleep for remainder of the second to maintain ~1Hz tick rate
        elapsed = time.time() - start_time
        sleep_dur = 1.0 - elapsed
        if sleep_dur > 0:
            time.sleep(sleep_dur)

if __name__ == '__main__':
    print("Miku Emotion Companion Backend Starting...")
    
    # Start WebSocket Server
    ws_server.start(handle_frontend_message)
    
    # Start Camera Acquisition
    if not camera.start():
        print("Fatal: Could not initialize camera. Exiting...")
        ws_server.stop()
        sys.exit(1)
        
    try:
        # Start main loop
        main_loop()
    except KeyboardInterrupt:
        print("Backend: Exiting on user interrupt...")
    finally:
        is_running = False
        camera.stop()
        ws_server.stop()
        print("Miku Emotion Companion Backend Cleaned Up.")
