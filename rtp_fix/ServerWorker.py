from random import randint
import sys, traceback, threading, socket

from VideoStream import VideoStream
from RtpPacket import RtpPacket

class ServerWorker:
    SETUP = 'SETUP'
    PLAY = 'PLAY'
    PAUSE = 'PAUSE'
    TEARDOWN = 'TEARDOWN'
    
    INIT = 0
    READY = 1
    PLAYING = 2
    state = INIT

    OK_200 = 0
    FILE_NOT_FOUND_404 = 1
    CON_ERR_500 = 2
    
    clientInfo = {}
    
    def __init__(self, clientInfo):
        self.clientInfo = clientInfo
        
    def run(self):
        threading.Thread(target=self.recvRtspRequest).start()
    
    def recvRtspRequest(self):
        """Receive RTSP request from the client."""
        connSocket = self.clientInfo['rtspSocket'][0]
        while True:            
            data = connSocket.recv(256)
            if data:
                print("Data received:\n" + data.decode("utf-8"))
                self.processRtspRequest(data.decode("utf-8"))
    
    def processRtspRequest(self, data):
        """Process RTSP request sent from the client."""
        # Get the request type
        request = data.split('\n')
        line1 = request[0].split(' ')
        requestType = line1[0]
        
        # Get the media file name
        filename = line1[1]
        
        # Get the RTSP sequence number 
        seq = request[1].split(' ')
        
        # Process SETUP request
        if requestType == self.SETUP:
            if self.state == self.INIT:
                print("processing SETUP\n")
                try:
                    self.clientInfo['videoStream'] = VideoStream(filename)
                    self.state = self.READY
                except IOError:
                    self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])
                
                self.clientInfo['session'] = randint(100000, 999999)
                self.replyRtsp(self.OK_200, seq[1])
                self.clientInfo['rtpPort'] = request[2].split(' ')[3]
        
        # Process PLAY request 		
        elif requestType == self.PLAY:
            if self.state == self.READY:
                print("processing PLAY\n")
                self.state = self.PLAYING
                self.clientInfo['rtpSocket'] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.replyRtsp(self.OK_200, seq[1])
                self.clientInfo['event'] = threading.Event()
                self.clientInfo['worker'] = threading.Thread(target=self.sendRtp) 
                self.clientInfo['worker'].start()
        
        # Process PAUSE request
        elif requestType == self.PAUSE:
            if self.state == self.PLAYING:
                print("processing PAUSE\n")
                self.state = self.READY
                self.clientInfo['event'].set()
                self.replyRtsp(self.OK_200, seq[1])
        
        # Process TEARDOWN request
        elif requestType == self.TEARDOWN:
            print("processing TEARDOWN\n")
            self.clientInfo['event'].set()
            self.replyRtsp(self.OK_200, seq[1])
            self.clientInfo['rtpSocket'].close()
            
    def sendRtp(self):
        """Send RTP packets over UDP."""
        while True:
            self.clientInfo['event'].wait(0.05) 
            
            if self.clientInfo['event'].isSet(): 
                break 
                
            data = self.clientInfo['videoStream'].nextFrame()
            if data: 
                frameNumber = self.clientInfo['videoStream'].frameNbr()
                try:
                    address = self.clientInfo['rtspSocket'][1][0]
                    port = int(self.clientInfo['rtpPort'])
                    
                    # --- XỬ LÝ PHÂN MẢNH (FRAGMENTATION) ---
                    MAX_RTP_PAYLOAD = 1400 
                    
                    data_len = len(data)
                    curr_pos = 0
                    
                    # Nếu ảnh nhỏ hơn 1400 byte thì gửi luôn 1 gói
                    if data_len <= MAX_RTP_PAYLOAD:
                        self.clientInfo['rtpSocket'].sendto(self.makeRtp(data, frameNumber, 1), (address, port))
                    else:
                        # Nếu ảnh lớn, chia nhỏ ra
                        while curr_pos < data_len:
                            chunk = data[curr_pos : curr_pos + MAX_RTP_PAYLOAD]
                            curr_pos += len(chunk)
                            
                            if curr_pos >= data_len:
                                marker = 1 # Mảnh cuối cùng
                            else:
                                marker = 0 # Mảnh giữa
                            
                            # Gửi chunk (mảnh nhỏ) thay vì data (toàn bộ)
                            self.clientInfo['rtpSocket'].sendto(self.makeRtp(chunk, frameNumber, marker), (address, port))
                        
                except:
                    print("Connection Error")

    def makeRtp(self, payload, frameNbr, marker=0):
        """RTP-packetize the video data."""
        version = 2
        padding = 0
        extension = 0
        cc = 0
        # marker lấy từ tham số truyền vào
        pt = 26 # MJPEG type
        seqnum = frameNbr
        ssrc = 0 
        
        rtpPacket = RtpPacket()
        rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload)
        
        return rtpPacket.getPacket()
        
    def replyRtsp(self, code, seq):
        """Send RTSP reply to the client."""
        if code == self.OK_200:
            reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + '\nSession: ' + str(self.clientInfo['session'])
            connSocket = self.clientInfo['rtspSocket'][0]
            connSocket.send(reply.encode())
        
        elif code == self.FILE_NOT_FOUND_404:
            print("404 NOT FOUND")
        elif code == self.CON_ERR_500:
            print("500 CONNECTION ERROR")