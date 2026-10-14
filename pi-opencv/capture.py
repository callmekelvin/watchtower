import time
import cv2 as cv
import threading
import datetime
import os

# Create the file names based on the date and camera no.
def file_output_name(cam):
    current_time = datetime.datetime.now()
    current_time_str = current_time.strftime("%Y_%m_%d__%H_%M_%S")

    vid_file_name = f"{current_time_str}_cam{cam}.avi"
    txt_file_name = f"{current_time_str}_cam{cam}.txt"

    return vid_file_name, txt_file_name, current_time

# Calculate elapsed time
def elapsed_time(start_time):
    ending_time = datetime.datetime.now()
    
    time_delta = ending_time - start_time
    elapsed_time_string = time_delta
    
    return elapsed_time_string, ending_time

# Format date strings
def format_write_string(time):
    time_string = time.strftime("Date: %Y/%m/%d - Time: %H:%M:%S\n\n")

    return time_string

# Creates TXT file with time info about video
def write_vid_info(txt_file_name, start_time):
    info_txt = open(txt_file_name, "w")

    info_txt.write("Starting Time:\n")
    info_txt.write(format_write_string(start_time))
    
    elapsed_time_string, ending_time = elapsed_time(start_time)

    info_txt.write("\nEnding Time:\n")
    info_txt.write(format_write_string(ending_time))

    info_txt.write("\nElapsed Time:\n")
    info_txt.write(f"{elapsed_time_string}")

    return 0

def sort_by_timestamp(val):
    return val[1]

def is_available_space(percentage_free):
    if (percentage_free <= 0.4):
        return False
    else:
        return True

# Ensure there is sufficient storage space on device to store videos
def free_space():
    current_dir = os.getcwd()
    recordings = []
    
    for root, dirs, files in os.walk(current_dir):
        if 'venv' in dirs:
            dirs.remove('venv')
            
        for name in files:
            if (name.endswith(".txt") or name.endswith(".avi")):
                recordings.append((name, os.path.getmtime(current_dir + "/" + name)))
    
    recordings.sort(key=sort_by_timestamp, reverse=True)
    # print(recordings)
    
    available_space = get_space()
    
    # delete videos as required to obtain storage space
    while(not is_available_space(available_space)):
        assert(len(recordings) >= 1)
        
        delete_file = recordings.pop()
        
        if (os.path.isfile(current_dir + "/" + delete_file[0])):
            os.remove(current_dir + "/" + delete_file[0])
        
        available_space = get_space()
        
# get current storage space on device                
def get_space():
    stats = os.statvfs("/")
    free = stats.f_bavail * stats.f_frsize
    total = stats.f_blocks * stats.f_frsize
    
    percentage_free = free / total
    
    print(f"Free: {free}, Total: {total}, Percent: {percentage_free}")
    
    return percentage_free
       
# Capture Video from Camera
def video_capture(cam, thread_lock):
    resume = True
    
    while(resume):
        vid = cv.VideoCapture(cam)

        # Verify that video input is received
        if vid is None or not vid.isOpened():
            print(f"No Camera Source from Camera No: {cam}")

        print(f"Starting Video Capture - Camera {cam}\n")

        file_name, txt_file_name, start_time = file_output_name(cam)

        # Define the codec and create VideoWriter object
        fourcc = cv.VideoWriter_fourcc(*'MJPG')
        
        # check + make space for new video and text file
        thread_lock.acquire()
        available_space = get_space()
        
        if(not is_available_space(available_space)):
            free_space()
            
        thread_lock.release()
        
        outputvid = cv.VideoWriter(file_name, fourcc, 10.0, (640,480))
        
        start_hour = time.localtime()[3]
        while(1):
            # Grabs, decodes and returns the next video frame.
            ret, image = vid.read()
            if (ret == 1):
                outputvid.write(image)
        
                # debug => display captured image
                # cv.imshow(f"Camera {cam}", image)

                # waits for user to input char 'q' to end capture or ends after a certain amount of time (an hour)
                if (start_hour != time.localtime()[3]):
                    break
                elif (cv.waitKey(1) & 0xFF == ord('q')):
                    resume = False
                    break
                
            else:
                resume = False
                break

        write_vid_info(txt_file_name, start_time)

        # When everything done, release the capture
        vid.release()
        outputvid.release()

    return 0

def checkCameraSource(camera_list):
    for i in camera_list:
        camera = cv.VideoCapture(f"/dev/video{i}")
        
        if camera is None or not camera.isOpened():
            print(f"No Camera Source from Camera No: {i}")
            exit(1)

def main(): 
    # Run Detect Linux Cameras Shell Script to determine device list
    # Based off device list, populate camera_list accordingly
    camera_list = [0, 2]
    
    checkCameraSource(camera_list)
    
    thread_lock = threading.Lock()
    
    threads_list = []
    for camera in camera_list:
        capture_thread = threading.Thread(target=video_capture, args=[camera, thread_lock])
        threads_list.append(capture_thread)
    
    # start all camera capture threads
    for thread in threads_list:
        thread.start()
    
    # wait for all camera capture threads to finish before terminating
    for thread in threads_list:
        thread.join()
    
    cv.destroyAllWindows()
    
    return 0
    

if __name__ == "__main__":
    main()
