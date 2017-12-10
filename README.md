# 2ping Micro - Minimal 2ping Daemon for Microcontrollers

2ping-micro is [2ping](https://www.finnie.org/software/2ping/) daemon written to run on microcontrollers, using [MicroPython](https://micropython.org/).
It has been tested on [ESP8266](https://en.wikipedia.org/wiki/ESP8266) and Unix ports of MicroPython, but should work on any MicroPython-capable microcontroller with at least 64 KiB memory.

This port is fully compliant with the [2ping protocol](https://github.com/rfinnie/2ping/blob/master/doc/2ping-protocol.md), but includes the bare minimum functionality.
Namely, it does not keep a state table and does not respond to client investigation requests, so it is not useful as an endpoint for determining directional packet loss (but is fine for detecting packet loss in general).

Supported features:

* 2-way ping responses
* Checksum verification and sending
* Program version reply
* IPv6 support (on supported MicroPython ports)
* GPIO LED flashing on incoming packets
* Battery measurement and reporting via ADC pin

Missing features:

* Client functionality
* 3-way pings
* Packet loss investigation support
* Cryptographic message authentication
* Host processing latency measurements
* Various extended spec functionality (RNG data, monotonic clock, notices, etc)

Note that this program is meant to be a proof of concept.
If you are looking at building your own full 2ping implementation, you are advised to read [the protocol spec](https://github.com/rfinnie/2ping/blob/master/doc/2ping-protocol.md) rather than look at this code, which was written for minimal processing, low memory, avoiding floating point math, etc.

## Installation

Install MicroPython on your target device.
As an example, [here are instructions for the ESP8266](http://docs.micropython.org/en/latest/esp8266/esp8266/tutorial/intro.html).

Configure the microcontroller for networking.
[This is easy with the ESP8266](http://docs.micropython.org/en/latest/esp8266/esp8266/tutorial/network_basics.html), and it's recommended the network initialization code be written to boot.py.

Copy twopingmicro.py to the target device, preferably as a separate file.
Here's a quick and dirty (and insecure) example to listen for a TCP connection and write the incoming connection's contents:

```
FILE = 'twopingmicro.py'
PORT = 9999
import usocket as socket
serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
serversocket.bind(socket.getaddrinfo('0.0.0.0', PORT)[0][-1])
serversocket.listen(1)
(clientsocket, address) = serversocket.accept()
f = open(FILE, 'w')
while True:
    buf = clientsocket.recv(1024)
    if not buf:
        break
    f.write(buf)
f.close()
serversocket.close()
```

Set up main.py to start twopingmicro.
The following code will start it unless canceled with 5 seconds via Ctrl-C (at which point you'd be back at the REPL):

```
import time
print('Starting in 5')
time.sleep(5)
import twopingmicro
twopingmicro.main({'debug': True, 'led': True})
```

When 'led' is enabled, it defaults to pin 2, which should be the default Wifi diagnostic LED on ESP8266.
On other platforms (when supported), this is highly dependent on the microcontroller.

Reset and test!

```
$ 2ping -c 3 --verbose 10.9.8.121
2PING 10.9.8.121 (10.9.8.121): 128 to 512 bytes of data.
SEND: <Packet (0xfd9d4ad138b3): [<Reply Requested>, <Extended: [<Version: 2ping 3.2.1 - Linux (Ubuntu) x86_64>]>]>
RECV: <Packet (0xf29638ef9d01): [<In Reply To: 0xfd9d4ad138b3>, <Extended: [<Version: 2ping MicroPython>]>]>
128 bytes from 10.9.8.121: ping_seq=1 time=62.578 ms
SEND: <Packet (0xf38a658c9fc6): [<Reply Requested>, <Extended: [<Version: 2ping 3.2.1 - Linux (Ubuntu) x86_64>]>]>
RECV: <Packet (0x68f38ca842e1): [<In Reply To: 0xf38a658c9fc6>, <Extended: [<Version: 2ping MicroPython>]>]>
128 bytes from 10.9.8.121: ping_seq=2 time=61.528 ms
SEND: <Packet (0xe20b5ba9de41): [<Reply Requested>, <Extended: [<Version: 2ping 3.2.1 - Linux (Ubuntu) x86_64>]>]>
RECV: <Packet (0x53c332a4d5a2): [<In Reply To: 0xe20b5ba9de41>, <Extended: [<Version: 2ping MicroPython>]>]>
128 bytes from 10.9.8.121: ping_seq=3 time=59.904 ms

--- 10.9.8.121 2ping statistics ---
3 pings transmitted, 3 received, 0% ping loss, time 2s 63ms
0 outbound ping losses (0%), 0 inbound (0%), 0 undetermined (0%)
rtt min/avg/ewma/max/mdev = 59.904/61.337/62.129/62.578/1.100 ms
3 raw packets transmitted, 3 received
```

## Battery support

2ping-micro supports battery measurement via an ADC pin and reporting via the new draft (as of this writing) [2ping 0x88a1f7c7 battery level extended segment](https://github.com/rfinnie/2ping/blob/master/doc/2ping-protocol.md#0x88a1f7c7---battery-levels).
This functionality is configurable, but assuming a 4.2V max battery is voltage divided via a 1M(R1) and 220K(R2) resistor and an ESP8266, it will work out of the box.
[This guide from Adafruit](https://learn.adafruit.com/using-ifttt-with-adafruit-io/wiring#battery-tracking) explains how to set up the battery/ADC circuitry.

On platforms without ADC support, if enabled it will simulate a battery, giving a random value each time.
