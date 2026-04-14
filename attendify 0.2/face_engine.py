import cv2
import face_recognition
import numpy as np
import time
import os
import pickle


def get_valid_rgb(frame):
    """Convert frame to valid RGB format for face_recognition"""
    if frame is None:
        return None
    
    # Ensure numpy array
    if not isinstance(frame, np.ndarray):
        return None
    
    try:
        # First check what we have
        if len(frame.shape) != 3:
            # Either 2D (grayscale) or flat - handle differently
            if len(frame.shape) == 2:
                # Grayscale - convert to RGB
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
            else:
                return None
        elif frame.shape[2] == 1:
            # Single channel but 3D - squeeze to 2D then convert
            frame = frame.squeeze()
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
        elif frame.shape[2] == 4:
            # RGBA - convert to BGR first then RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        elif frame.shape[2] == 3:
            # BGR (OpenCV default) - convert to RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        else:
            return None
        
        # Final validation
        if frame is None or len(frame.shape) != 3 or frame.shape[2] != 3:
            return None
        if frame.dtype != np.uint8:
            frame = frame.astype(np.uint8)
            
        return frame
    except Exception as e:
        print(f"Error in get_valid_rgb: {e}")
        return None


def capture_face_images(student_id, num_images=10):
    """Capture multiple face images for a student with space bar control"""
    try:
        # Clean up
        cv2.destroyAllWindows()
        time.sleep(0.5)
        
        # Create folder
        student_folder = f"static/faces/student_{student_id}"
        os.makedirs(student_folder, exist_ok=True)
        
        print("Opening camera...")
        
        # Use DirectShow backend to avoid MSMF issues on Windows
        cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        
        if not cam.isOpened():
            # Try fallback to default backend
            print("DirectShow failed, trying default backend...")
            cam = cv2.VideoCapture(0)
            if not cam.isOpened():
                print("ERROR: Cannot open camera")
                return None

        print("Camera opened successfully!")
        print("Warming up camera...")
        
        # Warmup frames
        for _ in range(30):
            cam.read()
        time.sleep(0.5)

        captured_count = 0
        image_paths = []

        # Create window
        cv2.namedWindow('Face Registration - Press SPACE to capture, ESC to exit')
        
        print(f"\n=== INSTRUCTIONS ===")
        print(f"Show your face in the camera window")
        print(f"Press SPACE to capture each image")
        print(f"Press ESC to finish early")
        print(f"Need to capture: {num_images} images")
        print(f"====================\n")

        while captured_count < num_images:
            ret, frame = cam.read()
            
            if not ret:
                print("Warning: Failed to read frame")
                continue
            
            # Create display frame with instructions
            display_frame = frame.copy()
            
            # Add text overlay
            cv2.putText(display_frame, f"Images: {captured_count}/{num_images}", 
                       (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.putText(display_frame, "Press SPACE to capture | ESC to finish", 
                       (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            
            # Try to detect face for preview
            rgb = get_valid_rgb(frame)
            if rgb is not None:
                try:
                    locations = face_recognition.face_locations(rgb, model="hog")
                    if locations:
                        # Draw rectangle around face
                        top, right, bottom, left = locations[0]
                        cv2.rectangle(display_frame, (left, top), (right, bottom), (0, 255, 0), 2)
                        cv2.putText(display_frame, "Face detected!", 
                                   (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                except:
                    pass
            
            # Show frame
            cv2.imshow('Face Registration - Press SPACE to capture, ESC to exit', display_frame)
            
            # Wait for key press
            key = cv2.waitKey(1) & 0xFF
            
            # Space bar = 32
            if key == 32:
                # Save image
                img_path = f"{student_folder}/face_{captured_count + 1}.jpg"
                cv2.imwrite(img_path, frame)
                image_paths.append(img_path)
                captured_count += 1
                print(f"Captured {captured_count}/{num_images}")
                
                # Brief flash effect
                flash_frame = display_frame.copy()
                flash_frame[:] = (255, 255, 255)
                cv2.imshow('Face Registration - Press SPACE to capture, ESC to exit', flash_frame)
                cv2.waitKey(100)
            
            # ESC = 27
            elif key == 27:
                print("User pressed ESC to finish")
                break

        cam.release()
        cv2.destroyAllWindows()

        if image_paths:
            print(f"Success! Captured {len(image_paths)} images")
            return pickle.dumps(image_paths)
        else:
            print("No face images captured")
            return None
        
    except Exception as e:
        print(f"ERROR: {e}")
        try:
            cv2.destroyAllWindows()
        except:
            pass
        return None


def verify_face(stored_encoding):
    """Verify face against stored encodings with live preview"""
    try:
        cv2.destroyAllWindows()
        time.sleep(0.5)
        
        # Use DirectShow backend to avoid MSMF issues on Windows
        cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cam.isOpened():
            # Try fallback
            print("DirectShow failed, trying default backend...")
            cam = cv2.VideoCapture(0)
            if not cam.isOpened():
                print("ERROR: Cannot open camera")
                return False, None

        for _ in range(30):
            cam.read()
        time.sleep(0.5)
        
        # Create window for verification
        cv2.namedWindow('Face Verification - Look at camera, ESC to exit')
        print("\n=== VERIFICATION INSTRUCTIONS ===")
        print("Look at the camera window")
        print("Press ESC to exit")
        print("=================================\n")

        # Load stored encodings
        try:
            stored_paths = pickle.loads(stored_encoding)
            if isinstance(stored_paths, list):
                stored_encodings = []
                for path in stored_paths:
                    if os.path.exists(path):
                        img = cv2.imread(path)
                        if img is not None:
                            rgb = get_valid_rgb(img)
                            if rgb is not None:
                                try:
                                    encs = face_recognition.face_encodings(rgb)
                                    if encs:
                                        stored_encodings.append(encs[0])
                                except:
                                    continue
        except:
            stored = np.frombuffer(stored_encoding, dtype=np.float32)
            stored_encodings = [stored]

        verified = False

        start_time = time.time()
        timeout = 30

        while (time.time() - start_time) < timeout:
            ret, frame = cam.read()
            if not ret:
                continue

            # Create display frame
            display_frame = frame.copy()
            
            # Add status text
            elapsed = int(time.time() - start_time)
            cv2.putText(display_frame, f"Time: {elapsed}s/30s", 
                       (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            # Check for ESC key
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC
                print("User pressed ESC to exit")
                break

            rgb = get_valid_rgb(frame)
            if rgb is None:
                cv2.imshow('Face Verification - Look at camera, ESC to exit', display_frame)
                continue
                
            try:
                locations = face_recognition.face_locations(rgb, model="hog")
            except:
                cv2.imshow('Face Verification - Look at camera, ESC to exit', display_frame)
                continue

            if locations:
                # Draw rectangle around face
                top, right, bottom, left = locations[0]
                cv2.rectangle(display_frame, (left, top), (right, bottom), (0, 255, 0), 2)
                
                try:
                    encs = face_recognition.face_encodings(rgb, locations)
                    for enc in encs:
                        for stored_enc in stored_encodings:
                            dist = np.linalg.norm(enc - stored_enc)
                            if dist < 0.6:
                                verified = True
                                cv2.putText(display_frame, "VERIFIED!", 
                                           (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 
                                           0.8, (0, 255, 0), 2)
                                break
                except:
                    pass
            
            cv2.imshow('Face Verification - Look at camera, ESC to exit', display_frame)
                    
            if verified:
                break

        cam.release()
        cv2.destroyAllWindows()
        return verified, None
        
    except Exception as e:
        print(f"ERROR in verify_face: {e}")
        try:
            cv2.destroyAllWindows()
        except:
            pass
        return False, None


def verify_face_auto(all_students_data):
    """
    Verify face automatically against all registered students.
    Returns (student_id, student_name, unknown_detected) 
    - matched: (student_id, student_name, False)
    - unknown face: (None, None, True)
    - no face/timeout: (None, None, False)
    
    all_students_data: list of tuples [(id, name, face_encoding), ...]
    """
    try:
        cv2.destroyAllWindows()
        time.sleep(0.5)
        
        # Use DirectShow backend
        cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cam.isOpened():
            print("DirectShow failed, trying default backend...")
            cam = cv2.VideoCapture(0)
            if not cam.isOpened():
                print("ERROR: Cannot open camera")
                return None, None, False  # No face shown

        print("Camera opened for auto-verification!")
        
        # Set camera to return consistent format
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        # Warmup
        for _ in range(30):
            cam.read()
        time.sleep(0.5)
        
        # Load all student encodings
        all_encodings = []
        
        try:
            print(f"Loading encodings for {len(all_students_data)} students...")
            print(f"Current working directory: {os.getcwd()}")
            
            # Get list of all jpg files in project for debugging
            all_jpg_files = []
            for root, dirs, files in os.walk('.'):
                for f in files:
                    if f.endswith('.jpg'):
                        all_jpg_files.append(os.path.join(root, f))
            print(f"Found {len(all_jpg_files)} jpg files in project")
            
            for student_id, student_name, encoding_data in all_students_data:
                print(f"\nProcessing student {student_id}: {student_name}")
                print(f"  Encoding data type: {type(encoding_data)}, length: {len(encoding_data) if encoding_data else 0}")
                
                if encoding_data is None:
                    print(f"  Skipping - encoding_data is None")
                    continue
            
                # Try loading as list of paths (from capture_face_images)
                try:
                    stored_paths = pickle.loads(encoding_data)
                    print(f"  Unpickled data type: {type(stored_paths)}")
                    
                    if isinstance(stored_paths, list):
                        print(f"  Found {len(stored_paths)} image paths")
                        for path in stored_paths:
                            print(f"    Original path: {path}")
                            
                            # Try to find the file by matching filename
                            path_filename = os.path.basename(path)
                            actual_path = None
                            
                            # First try direct path
                            if os.path.exists(path):
                                actual_path = path
                            else:
                                # Search all jpg files for matching name
                                for jpg_file in all_jpg_files:
                                    if os.path.basename(jpg_file) == path_filename:
                                        print(f"    Found matching file: {jpg_file}")
                                        actual_path = jpg_file
                                        break
                            
                            if actual_path:
                                print(f"    File found at: {actual_path}")
                                img = cv2.imread(actual_path)
                                if img is not None:
                                    print(f"    Image loaded, shape: {img.shape}")
                                    rgb = get_valid_rgb(img)
                                    if rgb is not None:
                                        print(f"    RGB shape: {rgb.shape}, dtype: {rgb.dtype}")
                                        try:
                                            # Try to detect faces first with multiple models
                                            face_locs = face_recognition.face_locations(rgb, model="hog")
                                            print(f"    HOG faces: {len(face_locs)}")
                                            if not face_locs:
                                                face_locs = face_recognition.face_locations(rgb, model="cnn")
                                                print(f"    CNN faces: {len(face_locs)}")
                                            
                                            if face_locs and len(face_locs) > 0:
                                                # Use a fresh copy of rgb for encoding
                                                encs = face_recognition.face_encodings(rgb, face_locs)
                                                print(f"    Face encodings found: {len(encs)}")
                                                if encs:
                                                    all_encodings.append({
                                                        'id': student_id,
                                                        'name': student_name,
                                                        'encoding': encs[0]
                                                    })
                                                    print(f"    SUCCESS - Added encoding for {student_name}")
                                            else:
                                                print(f"    No faces detected in stored image")
                                        except Exception as e:
                                            print(f"    Error in face_encodings: {e}")
                                            continue
                            else:
                                print(f"    File NOT found in any location")
                except Exception as e:
                    print(f"  Error unpickling: {e}")
                    # Try loading as raw encoding bytes
                    try:
                        stored = np.frombuffer(encoding_data, dtype=np.float32)
                        print(f"  Loaded as numpy array, shape: {stored.shape}")
                        all_encodings.append({
                            'id': student_id,
                            'name': student_name,
                            'encoding': stored
                        })
                        print(f"  SUCCESS - Added raw encoding for {student_name}")
                    except Exception as e2:
                        print(f"  Error loading as numpy: {e2}")
        except Exception as e:
            print(f"ERROR loading encodings: {e}")
            import traceback
            traceback.print_exc()
        
        if not all_encodings:
            print("WARNING: No valid face encodings loaded - trying to continue anyway...")
            # Don't exit - continue to camera to show unknown detection
            # This allows testing even without registered faces
        else:
            print(f"Loaded {len(all_encodings)} student encodings for matching")
        
        # Create window
        cv2.namedWindow('Attendance - Look at camera, ESC to exit')
        
        print("\n=== ATTENDANCE MODE ===")
        print("Look at the camera - attendance will be marked automatically")
        print("Press ESC to exit")
        print("========================\n")
        
        matched_student = None
        matched_name = None
        unknown_detected = False
        
        start_time = time.time()
        timeout = 60  # 60 seconds to find a match
        
        while (time.time() - start_time) < timeout:
            ret, frame = cam.read()
            if not ret:
                continue
            
            # Create display frame
            display_frame = frame.copy()
            
            # Add instructions
            elapsed = int(time.time() - start_time)
            cv2.putText(display_frame, f"Time: {elapsed}s/60s", 
                       (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            if matched_student:
                cv2.putText(display_frame, f"ATTENDANCE MARKED: {matched_name}", 
                           (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            else:
                cv2.putText(display_frame, "Looking for face...", 
                           (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
            
            # Check for ESC key
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                print("User pressed ESC to exit")
                break
            
            # Convert frame to RGB using existing function
            rgb = get_valid_rgb(frame)
            if rgb is None:
                cv2.putText(display_frame, "Frame Error: Invalid format", 
                           (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                cv2.imshow('Attendance - Look at camera, ESC to exit', display_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    break
                continue
            
            # Try face detection - with error handling
            locations = []
            try:
                # Debug: print frame info
                print(f"Frame: shape={frame.shape}, dtype={frame.dtype}")
                print(f"RGB: shape={rgb.shape}, dtype={rgb.dtype}")
                locations = face_recognition.face_locations(rgb, model="hog")
            except Exception as e:
                # Show error on screen but continue
                cv2.putText(display_frame, f"Detection Error: {str(e)[:40]}", 
                           (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                cv2.imshow('Attendance - Look at camera, ESC to exit', display_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    break
                continue
            
            if locations:
                # Draw rectangle around face - always show white box for detected face
                top, right, bottom, left = locations[0]
                box_color = (255, 255, 255)  # White box
                label = "Face Detected"
                is_recognized = False
                
                # Try to match with known faces (but always show white box)
                try:
                    encs = face_recognition.face_encodings(rgb, locations)
                    if encs:
                        current_encoding = encs[0]
                        
                        # Compare with all stored encodings
                        for student_data in all_encodings:
                            dist = np.linalg.norm(current_encoding - student_data['encoding'])
                            if dist < 0.6:
                                matched_student = student_data['id']
                                matched_name = student_data['name']
                                box_color = (0, 255, 0)  # Green for recognized
                                label = student_data['name']
                                is_recognized = True
                                print(f"MATCH: {matched_name} (distance: {dist:.4f})")
                                break
                except Exception as e:
                    print(f"Encoding error: {e}")
                
                # Draw rectangle and label
                cv2.rectangle(display_frame, (left, top), (right, bottom), box_color, 3)
                cv2.putText(display_frame, label, 
                           (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 
                           0.8, box_color, 2)

            
            cv2.imshow('Attendance - Look at camera, ESC to exit', display_frame)
            
            if matched_student:
                # Show result for a moment before exiting
                cv2.waitKey(1500)
                break
        
        cam.release()
        cv2.destroyAllWindows()
        
        # Return result - if matched return student info, otherwise return None
        if matched_student:
            return matched_student, matched_name, False
        else:
            return None, None, True  # True means face was shown but not recognized
        
    except Exception as e:
        print(f"ERROR in verify_face_auto: {e}")
        import traceback
        traceback.print_exc()
        try:
            cv2.destroyAllWindows()
        except:
            pass
        return None, None, False
