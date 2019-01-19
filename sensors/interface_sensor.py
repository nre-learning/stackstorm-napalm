from datetime import datetime

from napalm import get_network_driver

from st2reactor.sensor.base import PollingSensor

IF_UP = 'napalm.InterfaceUp'
IF_DOWN = 'napalm.InterfaceDown'


class InterfaceSensor(PollingSensor):

    def __init__(self, sensor_service, config=None, poll_interval=5):
        super(InterfaceSensor, self).__init__(sensor_service=sensor_service,
                                               config=config,
                                               poll_interval=poll_interval)
        self._logger = self.sensor_service.get_logger(
            name=self.__class__.__name__
        )

    def setup(self):
        # Dictionary for tracking per-device known state
        # Top-level keys are the management IPs sent to NAPALM, and
        # information on each is contained below that
        self.device_state = {}

        # Generate dictionary of device objects per configuration
        # IP Address(key): Device Object(value)
        self.devices = self._get_devices()

    def _get_devices(self):
        """Generate a dictionary of devices

        This used to be a fancy dictionary comprehension, but the way that most
        NAPALM drivers handle optional_args, this was difficult to maintain.
        We're doing it this way now so that optional_args is only provided when
        we are explicitly setting "port". Otherwise, we don't want to pass in
        "optional_args", so NAPALM can use its default value for port.
        """

        devices = {}
        for device in self._config['devices']:
            port = self._get_port(device)
            if port:
                optional_args={
                    'port': port
                }
            else:
                optional_args={}

            devices[device['hostname']] = get_network_driver(device['driver'])(
                hostname=device['hostname'],
                username=self._get_creds(device['hostname'])['username'],
                password=self._get_creds(device['hostname'])['password'],
                optional_args={
                    'port': self._get_port(device)
                }
            )

        return devices

    def _get_port(self, device):
        port = device.get('port')
        if port:
            return str(port)
        else:
            return None

    def _get_creds(self, hostname):
        for device in self._config['devices']:
            if device['hostname'] == hostname:
                return self._config['credentials'][device['credentials']]

    def get_if_changes(self, last_interfaces, this_interfaces):

        ifs_down = []
        ifs_up = []

        for iface_name, iface_details in last_interfaces.items():

            if iface_details['is_up'] and not this_interfaces[iface_name]['is_up']:
                ifs_down.append(iface_name)

            if not iface_details['is_up'] and this_interfaces[iface_name]['is_up']:
                ifs_up.append(iface_name)

        return ifs_down, ifs_up

    def poll(self):

        for hostname, device_obj in self.devices.items():

            # Skip if device not online
            try:
                device_obj.open()
            except Exception:
                # Currently, we just skip the device. if we can't reach it.
                # In the future it may be worth doing something with
                # the interface count after a few misses, as in this state,
                # the sensor will continue to report that a device has the
                # same number of interfaces even if the device is inaccessible
                self._logger.warn(
                    "Failed to open connection to %s. Skipping this device for now." % hostname
                )
                continue

            try:
                last_interfaces = self.device_state[hostname]["last_interfaces"]
            except KeyError:

                # No existing state; create the state and go to the next device.
                self.device_state[hostname] = {
                    "last_interfaces": device_obj.get_interfaces()
                }
                continue

            this_interfaces = device_obj.get_interfaces()

            ifs_down, ifs_up = self.get_if_changes(last_interfaces, this_interfaces)

            for ifdown in ifs_down:
                self._interface_updown_trigger(IF_DOWN, hostname, ifdown)

            for ifup in ifs_up:
                self._interface_updown_trigger(IF_UP, hostname, ifdown)

            # Save this state for the next poll
            self.device_state[hostname]["last_interfaces"] = this_interfaces

    def cleanup(self):
        # This is called when the st2 system goes down. You can perform
        # cleanup operations like closing the connections to external
        # system here.
        pass

    def add_trigger(self, trigger):
        # This method is called when trigger is created
        pass

    def update_trigger(self, trigger):
        # This method is called when trigger is updated
        pass

    def remove_trigger(self, trigger):
        # This method is called when trigger is deleted
        pass

    def _interface_updown_trigger(self, trigger, hostname, interface):
        payload = {
            'device': hostname,
            'interface': interface,
        }
        self._sensor_service.dispatch(trigger=trigger, payload=payload)
