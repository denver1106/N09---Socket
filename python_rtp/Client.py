from tkinter import *
import tkinter.messagebox as tkMessageBox
from PIL import Image, ImageTk
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

		# jitter để đo độ trễ mạng (gói trước đó và gói hiện tại)
		# self.jitter = 0.0 

		# lưu thời gian packet đến thực tế của gói trước đó
		# self.pre_arrival = 0.0 

		# lưu thời gian packet được gửi từ server của gói trước đó
		# self.pre_timestamp = 0.0 

		# danh sách hàng đợi buffer pritorityQueue (đẩy packet/frame vào đúng thứ tự sequence number), max hàng đợi là 200 packet/frame
		self.buffer = queue.PriorityQueue(maxsize=200)

		# số frame cần đạt trong hàng đợi buffer trước khi bắt đầu hiển thị video
		self.N_PRE_BUFFER = 20

		# biến theo dõi nạp frame vào buffer
		self.is_pre_buffering = True

		
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
		self.master.destroy() # Close the gui window
		os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT) # Delete the cache image from video

	def pauseMovie(self):
		"""Pause button handler."""
		if self.state == self.PLAYING:
			self.sendRtspRequest(self.PAUSE)
	
	def playMovie(self):
		"""Play button handler."""
		if self.state == self.READY:
			# Reset biến theo dõi buffer để bắt đầu nạp
			self.is_pre_buffering = True

			# Create a new thread to listen for RTP packets (để nạp vào buffer)
			# Thay vì ban đầu listenRtp nhận tới đâu hiện tới đó, thì bây giờ sẽ chỉ nhận để đẩy vào buffer để tránh hiện tượng giật lag
			threading.Thread(target=self.listenRtp).start()

			# Lấy frame từ buffer để chạy video
			threading.thread(target=self.handleBuffer).start()

			self.playEvent = threading.Event()
			self.playEvent.clear()
			self.sendRtspRequest(self.PLAY)
	
	def listenRtp(self):		
		"""Listen for RTP packets."""
		while True:
			try:
				data = self.rtpSocket.recv(20480)
				if data:
					# curr_arrival = time.time()

					rtpPacket = RtpPacket() #tạo RtpPacket
					rtpPacket.decode(data) #tách header RTP + payload 

					curr_seq = rtpPacket.seqNum()
					print("Current Seq Num: " + str(curr_seq))
					# curr_timestamp = rtpPacket.timestamp()
					
					
					# if self.frameNbr > 0 and self.pre_arrival > 0:
					# 	delta_arrival = curr_arrival - self.pre_arrival
					# 	delta_timestamp = (curr_timestamp - self.pre_timestamp) / 20.0
					# 	D = abs(delta_arrival - delta_timestamp)
					# 	self.jitter = self.jitter + (D - self.jitter) / 16.0

					# 	# print(f"Seq: {curr_seq} | Jitter: {self.jitter:.5f}")
					
					# # cập nhật pre arrival và pre timestamp cho lần tính toán tiếp theo
					# self.pre_arrival = curr_arrival
					# self.pre_timestamp = curr_timestamp
					
					# nếu frame number hiện tại lớn hơn frame number trước đó => đúng thứ tự gói tin 
					if curr_seq > self.frameNbr: 
						# đẩy vào buffer
						self.buffer.put((curr_seq, rtpPacket.getPayload()))
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
				print("Enough frame in buffer!")

			# Nếu buffer không trống
			if not self.buffer.empty():
				seqNum, data = self.buffer.get()
				self.frameNbr = seqNum
				self.updateMovie(self.writeFrame(data))

				# # fps_default = 0.05

				# # if self.jitter > 0.05 or current_buffer_size < 5:
				# # 	fps_reality = fps_default + 0.01
				# # elif current_buffer_size > 50:
				# # 	fps_reality = fps_default - 0.01
				# # else:
				# 	fps_reality = fps_default

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
		photo = ImageTk.PhotoImage(Image.open(imageFile))
		self.label.configure(image = photo, height=288) 
		self.label.image = photo
		
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
