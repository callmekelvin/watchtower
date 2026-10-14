#Detect All Linux Cameras

dir="/sys/class/video4linux/"
device_name="name"

output="Camera List for Linux Devices\n"

#Extract camera information from all cameras in directory
for device in "$dir"*; do
    device_info=$(cat "$device"/"$device_name")
    device_line="${device} ====> ${device_info}"
    output+="${device_line}\n"
    
done

echo -e "$output" > device_list