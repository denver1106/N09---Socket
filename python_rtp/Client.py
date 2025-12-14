from tkinter import *
import tkinter.messagebox as tkMessageBox
from PIL import Image, ImageTk
import io
import socket, threading, sys, traceback, os

from RtpPacket import RtpPacket

# Thư viện bổ trợ cho lưu buffer và tính toán jitter
import queue
import time


CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"

class Client:
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT
	
	SETUP = 0
	PLAY = 1
	PAUSE = 2
	TEARDOWN = 3
	
	# Initiation..
	def __init__(self, master, serveraddr, serverport, rtpport, filename):
		self.master = master
		self.master.protocol("WM_DELETE_WINDOW", self.handler)
		self.createWidgets()
		self.serverAddr = serveraddr
		self.serverPort = int(serverport)
		self.rtpPort = int(rtpport)
		self.fileName = filename
		self.rtspSeq = 0
		self.sessionId = 0
		self.requestSent = -1
		self.teardownAcked = 0
		self.connectToServer()
		self.frameNbr = 0

		# danh sách hàng đợi buffer pritorityQueue (đẩy packet/frame vào đúng thứ tự sequence number), max hàng đợi là 200 packet/frame
		self.buffer = queue.PriorityQueue(maxsize=200)

		# số frame cần đạt trong hàng đợi buffer trước khi bắt đầu hiển thị video
		self.N_PRE_BUFFER = 20

		# biến theo dõi nạp frame vào buffer
		self.is_pre_buffering = True

		# Biến hỗ trợ HD Streaming: Bộ đệm tạm để ghép các mảnh gói tin thành 1 frame hoàn chỉnh
		self.currentFrameBuffer = b""

		# Các biến thống kê (Analysis)
		self.statTotalRecv = 0      # Tổng số gói nhận được
		self.statLost = 0           # Tổng số gói bị mất
		self.lastRxSeq = 0          # Sequence number của gói nhận gần nhất

		
	def createWidgets(self):
		"""Build GUI."""
		# Create Setup button
		self.setup = Button(self.master, width=20, padx=3, pady=3)
		self.setup["text"] = "Setup"
		self.setup["command"] = self.setupMovie
		self.setup.grid(row=1, column=0, padx=2, pady=2)
		
		# Create Play button		
		self.start = Button(self.master, width=20, padx=3, pady=3)
		self.start["text"] = "Play"
		self.start["command"] = self.playMovie
		self.start.grid(row=1, column=1, padx=2, pady=2)
		
		# Create Pause button			
		self.pause = Button(self.master, width=20, padx=3, pady=3)
		self.pause["text"] = "Pause"
		self.pause["command"] = self.pauseMovie
		self.pause.grid(row=1, column=2, padx=2, pady=2)
		
		# Create Teardown button
		self.teardown = Button(self.master, width=20, padx=3, pady=3)
		self.teardown["text"] = "Teardown"
		self.teardown["command"] =  self.exitClient
		self.teardown.grid(row=1, column=3, padx=2, pady=2)
		
		# Create a label to display the movie
		self.label = Label(self.master, height=19)
		self.label.grid(row=0, column=0, columnspan=4, sticky=W+E+N+S, padx=5, pady=5) 
	
	def setupMovie(self):
		"""Setup button handler."""
		if self.state == self.INIT:
			self.sendRtspRequest(self.SETUP)
	
	def exitClient(self):
		"""Teardown button handler."""
		self.sendRtspRequest(self.TEARDOWN)		
		
		# In báo cáo Packet Loss khi đóng Client
		if self.statTotalRecv > 0:
			loss_rate = float(self.statLost) / (self.statTotalRecv + self.statLost) * 100
			print("\n------------------------------------------------")
			print("RTP PACKET LOSS REPORT")
			print("------------------------------------------------")
			print("Total Packets Received : %d" % self.statTotalRecv)
			print("Total Packets Lost     : %d" % self.statLost)
			print("Packet Loss Rate       : {:.2f}%".format(loss_rate))
			print("------------------------------------------------\n")

		self.master.destroy() # Close the gui window
		# Thêm try-except để tránh lỗi nếu file không tồn tại
		try:
			os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT) # Delete the cache image from video
		except:
			pass

	def pauseMovie(self):
		"""Pause button handler."""
		if self.state == self.PLAYING:
			if hasattr(self, 'playEvent') and self.playEvent is not None:
				self.playEvent.set()
			self.sendRtspRequest(self.PAUSE)
	
	def playMovie(self):
		"""Play button handler."""
		if hasattr(self, 'playEvent') and not self.playEvent.is_set():
			print("Video is already playing!")
			return
		
		if self.state == self.READY or self.state == self.PAUSE:
			# Reset biến theo dõi buffer để bắt đầu nạp lại
			self.playEvent = threading.Event()
			self.playEvent.clear()
			self.is_pre_buffering = True

			# Create a new thread to listen for RTP packets (để nạp vào buffer)
			# Thay vì ban đầu listenRtp nhận tới đâu hiện tới đó, thì bây giờ sẽ chỉ nhận để đẩy vào buffer để tránh hiện tượng giật lag
			threading.Thread(target=self.listenRtp).start()

			# Lấy frame từ buffer để chạy video
			threading.Thread(target=self.handleBuffer).start()

			
			self.sendRtspRequest(self.PLAY)
	
	def listenRtp(self):		
		"""Listen for RTP packets."""
		
		while True:
			try:
				data = self.rtpSocket.recv(65535)
				if data:
					rtpPacket = RtpPacket() #tạo RtpPacket
					rtpPacket.decode(data) #tách header RTP + payload 

					curr_seq = rtpPacket.seqNum()
					
					# Tính toán thống kê mất gói (Analysis)
					if self.lastRxSeq > 0 and curr_seq > self.lastRxSeq + 1:
						diff = curr_seq - self.lastRxSeq - 1
						self.statLost += diff
						print(f"[Analysis] Packet Loss Detected: Lost {diff} packets")
					
					self.statTotalRecv += 1
					self.lastRxSeq = curr_seq

					# Logic Reassembly cho HD Streaming
					# Thay vì đẩy ngay vào buffer, ta gom payload vào buffer tạm
					self.currentFrameBuffer += rtpPacket.getPayload()

					# Kiểm tra Marker bit để biết đây có phải gói cuối cùng của frame không
					if rtpPacket.getMarker() == 1:
						# Nếu đúng là gói cuối, và frame mới hơn frame đang hiện
						if curr_seq > self.frameNbr: 
							# đẩy frame hoàn chỉnh vào buffer
							self.buffer.put((curr_seq, self.currentFrameBuffer))
						
						# Reset buffer tạm để đón frame tiếp theo
						self.currentFrameBuffer = b""
						print("Current Seq Num: " + str(curr_seq))

			except:
				# Stop listening upon requesting PAUSE or TEARDOWN
				if self.playEvent.is_set(): 
					break
				
				# Upon receiving ACK for TEARDOWN request,
				# close the RTP socket
				if self.teardownAcked == 1:
					self.rtpSocket.shutdown(socket.SHUT_RDWR)
					self.rtpSocket.close()
					break

	def handleBuffer(self):
		while not self.playEvent.is_set():
			#Lấy số frame hiện tại
			current_buffer_size = self.buffer.qsize()

			# Nếu chưa đủ frame
			if self.is_pre_buffering:
				if current_buffer_size < self.N_PRE_BUFFER:
					# Chưa đủ frame yêu cầu, chờ nạp tiếp
					time.sleep(0.01)

					# Bỏ qua phần hiển thị bên dưới
					continue 
			else:
				# Đánh dấu đã nạp xong
				self.is_pre_buffering = False

			# Nếu buffer không trống
			if not self.buffer.empty():
				# Pop để lấy frame và data
				seqNum, data = self.buffer.get()
				self.frameNbr = seqNum
				self.updateMovie(self.writeFrame(data))
				time.sleep(0.05)
			
			else:
				print("Empty buffer. Reloading!")
				self.is_pre_buffering = True
				time.sleep(0.01)

	def writeFrame(self, data):
		"""Write the received frame to a temp image file. Return the image file."""
		cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
		file = open(cachename, "wb")
		file.write(data)
		file.close()
		
		return cachename
	
	def updateMovie(self, imageFile):
		"""Update the image file as video frame in the GUI."""
		# Thêm try-except để tránh crash nếu file ảnh bị lỗi do mất gói
		try:
			photo = ImageTk.PhotoImage(Image.open(imageFile))
			self.label.configure(image = photo, height=288) 
			self.label.image = photo
		except:
			print("[Client] Warning: Could not update frame (Bad image data)")
		
	def connectToServer(self):
		"""Connect to the Server. Start a new RTSP/TCP session."""
		self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			self.rtspSocket.connect((self.serverAddr, self.serverPort))
		except:
			tkMessageBox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr)
	
	def sendRtspRequest(self, requestCode):
		"""Send RTSP request to the server."""	
		
		# Setup request
		if requestCode == self.SETUP and self.state == self.INIT:
			threading.Thread(target=self.recvRtspReply).start()
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			request = 'SETUP {filename} RTSP/1.0\nCSeq:{sequenceNum}\nTransport: RTP/UDP; client_port={port}\n'.format(filename = str(self.fileName), sequenceNum = str(self.rtspSeq), port = str(self.rtpPort))
			
			# Keep track of the sent request.
			self.requestSent = self.SETUP
		
		# Play request
		elif requestCode == self.PLAY and self.state == self.READY:
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			request = 'PLAY {filename} RTSP/1.0\nCSeq:{sequenceNum}\nSession: {sessionID}\n'.format(filename = str(self.fileName), sequenceNum = str(self.rtspSeq), sessionID = str(self.sessionId))
			
			# Keep track of the sent request.
			self.requestSent = self.PLAY
		
		# Pause request
		elif requestCode == self.PAUSE and self.state == self.PLAYING:
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			request = 'PAUSE {filename} RTSP/1.0\nCSeq:{sequenceNum}\nSession: {sessionID}\n'.format(filename = str(self.fileName), sequenceNum = str(self.rtspSeq), sessionID = str(self.sessionId))
			# Keep track of the sent request.
			self.requestSent = self.PAUSE
			
		# Teardown request
		elif requestCode == self.TEARDOWN and not self.state == self.INIT:
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			request = 'TEARDOWN {filename} RTSP/1.0\nCSeq:{sequenceNum}\nSession: {sessionID}\n'.format(filename = str(self.fileName), sequenceNum = str(self.rtspSeq), sessionID = str(self.sessionId))
			
			# Keep track of the sent request.
			self.requestSent = self.TEARDOWN
		else:
			return
		
		# Send the RTSP request using rtspSocket
		self.rtspSocket.sendall(request.encode('utf-8'))
		
		print('\nData sent:\n' + request)
	
	def recvRtspReply(self):
		"""Receive RTSP reply from the server."""
		while True:
			reply = self.rtspSocket.recv(1024)
			
			if reply: 
				self.parseRtspReply(reply.decode("utf-8"))
			
			# Close the RTSP socket upon requesting Teardown
			if self.requestSent == self.TEARDOWN:
				self.rtspSocket.shutdown(socket.SHUT_RDWR)
				self.rtspSocket.close()
				break
	
	def parseRtspReply(self, data):
		"""Parse the RTSP reply from the server."""
		lines = data.split('\n')
		seqNum = int(lines[1].split(' ')[1])
		
		# Process only if the server reply's sequence number is the same as the request's
		if seqNum == self.rtspSeq:
			session = int(lines[2].split(' ')[1])
			# New RTSP session ID
			if self.sessionId == 0:
				self.sessionId = session
			
			# Process only if the session ID is the same
			if self.sessionId == session:
				if int(lines[0].split(' ')[1]) == 200: 
					if self.requestSent == self.SETUP:
						# Update RTSP state.
						self.state = self.READY
						
						# Open RTP port.
						self.openRtpPort() 
					elif self.requestSent == self.PLAY:
						self.state = self.PLAYING
					elif self.requestSent == self.PAUSE:
						self.state = self.READY
						
						# The play thread exits. A new thread is created on resume.
						self.playEvent.set()
					elif self.requestSent == self.TEARDOWN:
						self.state = self.INIT
						
						# Flag the teardownAcked to close the socket.
						self.teardownAcked = 1 
	
	def openRtpPort(self):
		"""Open RTP socket binded to a specified port."""

		# Create a new datagram socket to receive RTP packets from the server
		self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		
		# Set the timeout value of the socket to 0.5sec
		self.rtpSocket.settimeout(0.5)
		
		try:
			# Bind the socket to the address using the RTP port given by the client user
			self.rtpSocket.bind(('',self.rtpPort))
		except:
			tkMessageBox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtpPort)

	def handler(self):
		"""Handler on explicitly closing the GUI window."""
		self.pauseMovie()
		if tkMessageBox.askokcancel("Quit?", "Are you sure you want to quit?"):
			self.exitClient()
		else: # When the user presses cancel, resume playing.
			self.playMovie()