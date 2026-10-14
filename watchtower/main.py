from backend.usb_discovery import UsbDiscovery


def discover_cameras():
    # PyUSB - USB Devices Discovery
    usb_devices = UsbDiscovery().list_video_devices()
    print(usb_devices)


def main():
    cameras = discover_cameras()


if __name__ == "__main__":
    main()
