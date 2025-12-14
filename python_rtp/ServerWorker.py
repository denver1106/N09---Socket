from random import randint
import sys, traceback, threading, socket
import time

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
		# Khởi tạo số thứ tự gói tin RTP (Sequence Number)
		self.clientInfo['rtpSequenceNum'] = 0
		
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
		
		# Get the RTSP sequence number safely
		seq_line = request[1].replace("CSeq:", "").replace("CSeq", "").strip()
		
		try:
			seqNum = int(seq_line)
		except:
			print("Lỗi parse CSeq:", request[1], "(parsed:", seq_line, ")")
			return

		
		# Process SETUP request
		if requestType == self.SETUP:
			if self.state == self.INIT:
				# Update state
				print("processing SETUP\n")
				
				try:
					self.clientInfo['videoStream'] = VideoStream(filename)
					self.state = self.READY
				except IOError:
					self.replyRtsp(self.FILE_NOT_FOUND_404, seqNum)
				
				# Generate a randomized RTSP session ID
				self.clientInfo['session'] = randint(100000, 999999)
				
				# Send RTSP reply
				self.replyRtsp(self.OK_200, seqNum)
				
				# Parse RTP port safely from the Transport line
				transport_line = request[2]

				if "client_port=" in transport_line:
					try:
						# Thêm split('-')[0] cho trường hợp port range (vd: 25000-25001)
						port_str = transport_line.split("client_port=")[1].strip().split('-')[0]
						self.clientInfo['rtpPort'] = int(port_str)
					except:
						print("Lỗi parse RTP port:", transport_line)
				else:
					print("Không tìm thấy client_port trong Transport line:", transport_line)

		
		# Process PLAY request 		
		elif requestType == self.PLAY:
			if self.state == self.READY:
				print("processing PLAY\n")
				self.state = self.PLAYING
				
				# Create a new socket for RTP/UDP
				self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
				
				self.replyRtsp(self.OK_200, seqNum)
				
				# Create a new thread and start sending RTP packets
				self.clientInfo['event'] = threading.Event()
				self.clientInfo['worker']= threading.Thread(target=self.sendRtp) 
				self.clientInfo['worker'].start()
		
		# Process PAUSE request
		elif requestType == self.PAUSE:
			if self.state == self.PLAYING:
				print("processing PAUSE\n")
				self.state = self.READY
				
				self.clientInfo['event'].set()
			
				self.replyRtsp(self.OK_200, seqNum)
		
		# Process TEARDOWN request
		elif requestType == self.TEARDOWN:
			print("processing TEARDOWN\n")

			self.clientInfo['event'].set()
			
			self.replyRtsp(self.OK_200, seqNum)
			
			# Close the RTP socket
			try:
				self.clientInfo['rtpSocket'].close()
			except:
				pass
			
	def sendRtp(self):
		"""Send RTP packets over UDP."""
		while True:
			self.clientInfo['event'].wait(0.05) 
			
			# Stop sending if request is PAUSE or TEARDOWN
			if self.clientInfo['event'].isSet(): 
				break 
				
			data = self.clientInfo['videoStream'].nextFrame()
			
			if data: 
				frameNumber = self.clientInfo['videoStream'].frameNbr()
				
				try:
					address = self.clientInfo['rtspSocket'][1][0]
					port = int(self.clientInfo['rtpPort'])

					# FRAGMENTATION
					MAX_PAYLOAD_SIZE = 1400 
					
					size = len(data)
					offset = 0

					# Vòng lặp cắt frame lớn thành nhiều gói nhỏ
					while offset < size:
						# Tính điểm kết thúc của chunk hiện tại
						end = min(offset + MAX_PAYLOAD_SIZE, size)
						payload_chunk = data[offset:end]

						# Tăng Sequence Number cho MỖI GÓI TIN gửi đi
						self.clientInfo['rtpSequenceNum'] += 1
						
						# Xác định Marker Bit (M)
						# M = 1 nếu là mảnh cuối cùng của frame, ngược lại M = 0
						if end == size:
							marker = 1
						else:
							marker = 0

						# Truyền Sequence Number vào hàm makeRtp
						packet = self.makeRtp(payload_chunk, self.clientInfo['rtpSequenceNum'], marker)
						
						# Gửi gói tin
						self.clientInfo['rtpSocket'].sendto(packet, (address, port))
						
						# Tăng offset
						offset += MAX_PAYLOAD_SIZE
					
				except:
					print("Connection Error")
					#traceback.print_exc(file=sys.stdout)

	def makeRtp(self, payload, seqNum, marker=0):
		"""RTP-packetize the video data."""
		version = 2
		padding = 0
		extension = 0
		cc = 0
		pt = 26 # MJPEG type
		ssrc = 0 
		
		rtpPacket = RtpPacket()
		
		rtpPacket.encode(version, padding, extension, cc, seqNum, marker, pt, ssrc, payload)
		
		return rtpPacket.getPacket()
		
	def replyRtsp(self, code, seq):
		"""Send RTSP reply to the client."""
		if code == self.OK_200:
			#print("200 OK")
			reply = 'RTSP/1.0 200 OK\nCSeq: ' + str(seq) + '\nSession: ' + str(self.clientInfo['session'])
			connSocket = self.clientInfo['rtspSocket'][0]
			connSocket.send(reply.encode())
		
		# Error messages
		elif code == self.FILE_NOT_FOUND_404:
			print("404 NOT FOUND")
		elif code == self.CON_ERR_500:
			print("500 CONNECTION ERROR")