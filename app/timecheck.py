"""SNTP witness; never adjusts system time. Measurement failures fail closed."""
import socket
import struct
import time
from app.domain.market import now


def measure_clock(host):
    offset_epoch=2208988800
    request=bytearray(48);request[0]=0x23
    sent=time.time()
    seconds=int(sent)+offset_epoch;fraction=int((sent-int(sent))*2**32)
    struct.pack_into('!II',request,40,seconds,fraction)
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.settimeout(3)
        sock.connect((host,123));sock.send(request);response=sock.recv(512)
    received=time.time()
    if len(response)<48 or response[0]&7!=4 or response[0]>>6==3 or not 1<=response[1]<=15 or response[24:32]!=request[40:48]:
        raise ValueError('INVALID_NTP_RESPONSE')
    def ntp(position):
        sec,frac=struct.unpack_from('!II',response,position)
        return sec-offset_epoch+frac/2**32
    t2,t3=ntp(32),ntp(40)
    delay=(received-sent)-(t3-t2)
    if not 0<=delay<=1:raise ValueError('NTP_UNCERTAIN_DELAY')
    return {'source':'SNTP/'+host,'host':host,'checked_at':now().isoformat(),'offset_seconds':((t2-sent)+(t3-received))/2,'roundtrip_seconds':delay}
