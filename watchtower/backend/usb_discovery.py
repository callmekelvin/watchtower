from typing import List, Optional, Set, Tuple, Union

import libusb_package
import usb.core
import usb.util

from backend.models import PyUSBDescripters


class UsbDiscovery:
    def __init__(self):
        pass

    def list_video_devices(self) -> List[PyUSBDescripters]:
        video_usb_devices: List[PyUSBDescripters] = []
        seen: Set[Union[str, Tuple[int, int]]] = set()

        # Iterate over every USB Device connected to machine
        for device in libusb_package.find(find_all=True):
            # Store USB Device Information if it has a Video Interface
            if not self._has_video_interface(device):
                continue

            # Get USB Information
            usb_descripters = self._extract_usb_descripters(device)
            key = usb_descripters.serial or (usb_descripters.bus, usb_descripters.address)

            if key in seen:
                continue
            seen.add(key)
            video_usb_devices.append(usb_descripters)

        return video_usb_devices

    # Check for Video Interfaces from USB Device
    def _has_video_interface(self, device: usb.core.Device) -> bool:
        try:
            for configuration in device:
                # Interfaces list out function for USB Device
                for interface in configuration:
                    # Return True for USB Devices which contain Video Interfaces
                    if interface.bInterfaceClass == 0x0E:
                        return True
        except Exception:
            return False
        return False

    # Extract out USB Descripters from USB Device in PyUSB
    def _extract_usb_descripters(self, device: usb.core.Device) -> PyUSBDescripters:
        return PyUSBDescripters(
            id_vendor=device.idVendor,
            id_product=device.idProduct,
            serial=self._safe_string(device, device.iSerialNumber),
            manufacturer=self._safe_string(device, device.iManufacturer),
            product_name=self._safe_string(device, device.iProduct),
            bus=device.bus,
            address=device.address,
            port_path=self._port_path(device),
        )

    def _safe_string(self, device: usb.core.Device, index: int) -> Optional[str]:
        if not index:
            return None
        try:
            return usb.util.get_string(device, index)
        except Exception:
            return None

    def _port_path(self, device: usb.core.Device) -> Tuple[int, ...]:
        try:
            port_numbers = device.port_numbers
            if port_numbers:
                return tuple(port_numbers)
        except Exception:
            pass
        return ()
