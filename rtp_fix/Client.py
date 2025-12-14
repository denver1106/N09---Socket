from tkinter import *
import tkinter.messagebox
from tkinter import messagebox as tkMessageBox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os
import queue 

from RtpPacket import RtpPacket

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
		self.frameBuffer = b"" 
		self.cacheBuffer = queue.PriorityQueue(maxsize=1000) 
		self.BUFFER_THRESHOLD = 60
		self.isBufferPlaying = False 
		self.updateGUI()
		
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

		# 1. Thanh tiến trình Video (Progress Bar)
		self.progressLabel = Label(self.master, text="Video Progress")
		self.progressLabel.grid(row=2, column=0, padx=2, pady=2)
		
		self.progressScale = Scale(self.master, from_=0, to=4832, orient=HORIZONTAL, length=300)
		self.progressScale.grid(row=3, column=0, columnspan=4, padx=2, pady=2)

		# 2. Thanh hiển thị bộ đệm (Cache Bar)
		self.cacheLabel = Label(self.master, text="Buffer Level (Cache)")
		self.cacheLabel.grid(row=4, column=0, padx=2, pady=2)
		
		# Tạo Canvas để vẽ thanh Cache
		self.cacheCanvas = Canvas(self.master, width=300, height=20, bg='white', relief=SUNKEN, borderwidth=1)
		self.cacheCanvas.grid(row=5, column=0, columnspan=4, padx=2, pady=2)
		
		# Vẽ hình chữ nhật đại diện cho lượng data (ban đầu là 0)
		self.cacheBar = self.cacheCanvas.create_rectangle(0, 0, 0, 20, fill='blue')
	
	def setupMovie(self):
		"""Setup button handler."""
		if self.state == self.INIT:
			self.sendRtspRequest(self.SETUP)
	
	def exitClient(self):
		"""Teardown button handler."""
		self.sendRtspRequest(self.TEARDOWN)		
		self.master.destroy() 
		try:
			os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT) 
		except OSError:
			pass

	def pauseMovie(self):
		"""Pause button handler."""
		if self.state == self.PLAYING:
			self.sendRtspRequest(self.PAUSE)
	
	def playMovie(self):
		"""Play button handler."""
		if self.state == self.READY:
			threading.Thread(target=self.listenRtp).start()
			self.playEvent = threading.Event()
			self.playEvent.clear()
			self.sendRtspRequest(self.PLAY)
	
	def listenRtp(self):		
		"""Listen for RTP packets."""
		while True:
			try:
				data = self.rtpSocket.recv(65535)
				if data:
					rtpPacket = RtpPacket()
					rtpPacket.decode(data)
					
				self.frameBuffer += rtpPacket.getPayload()

				if rtpPacket.getMarker() == 1:
					currFrameNbr = rtpPacket.seqNum()

					if currFrameNbr > self.frameNbr: 
						self.frameNbr = currFrameNbr
                        
						self.cacheBuffer.put((currFrameNbr, self.frameBuffer))
                        
						if not self.isBufferPlaying and self.cacheBuffer.qsize() >= self.BUFFER_THRESHOLD:
							self.isBufferPlaying = True
							self.playMovieFromBuffer()

					self.frameBuffer = b""
			except:
				if self.playEvent.isSet(): 
					break
				
				if self.teardownAcked == 1:
					self.rtpSocket.shutdown(socket.SHUT_RDWR)
					self.rtpSocket.close()
					break
					
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
			self.rtspSeq = 0
			self.sessionId = 0          
			self.requestSent = -1
			self.teardownAcked = 0      
			self.frameNbr = 0
			
			self.cacheBuffer = queue.PriorityQueue(maxsize=1000) 
			
			self.packetLossCount = 0
			self.totalBytes = 0
			self.rtspSeq += 1 

			request = "SETUP " + str(self.fileName) + " RTSP/1.0\n" + \
					  "CSeq: " + str(self.rtspSeq) + "\n" + \
					  "Transport: RTP/UDP; client_port= " + str(self.rtpPort)
			self.requestSent = self.SETUP
		
		# Play request
		elif requestCode == self.PLAY and self.state == self.READY:
			self.rtspSeq += 1
			request = "PLAY " + str(self.fileName) + " RTSP/1.0\n" + \
					  "CSeq: " + str(self.rtspSeq) + "\n" + \
					  "Session: " + str(self.sessionId)
			self.requestSent = self.PLAY
		
		# Pause request
		elif requestCode == self.PAUSE and self.state == self.PLAYING:
			self.rtspSeq += 1
			request = "PAUSE " + str(self.fileName) + " RTSP/1.0\n" + \
					  "CSeq: " + str(self.rtspSeq) + "\n" + \
					  "Session: " + str(self.sessionId)
			self.requestSent = self.PAUSE
			
		# Teardown request
		elif requestCode == self.TEARDOWN and not self.state == self.INIT:
			self.rtspSeq += 1
			request = "TEARDOWN " + str(self.fileName) + " RTSP/1.0\n" + \
					  "CSeq: " + str(self.rtspSeq) + "\n" + \
					  "Session: " + str(self.sessionId)
			self.requestSent = self.TEARDOWN
		else:
			return
		
		self.rtspSocket.send(request.encode('utf-8'))
		print('\nData sent:\n' + request)
	
	def recvRtspReply(self):
		"""Receive RTSP reply from the server."""
		while True:
			reply = self.rtspSocket.recv(1024)
			
			if reply: 
				self.parseRtspReply(reply.decode("utf-8"))
			
			if self.requestSent == self.TEARDOWN:
				self.rtspSocket.shutdown(socket.SHUT_RDWR)
				self.rtspSocket.close()
				break
	
	def parseRtspReply(self, data):
		"""Parse the RTSP reply from the server."""
		lines = data.split('\n')
		seqNum = int(lines[1].split(' ')[1])
		
		if seqNum == self.rtspSeq:
			session = int(lines[2].split(' ')[1])
			if self.sessionId == 0:
				self.sessionId = session
			
			if self.sessionId == session:
				if int(lines[0].split(' ')[1]) == 200: 
					if self.requestSent == self.SETUP:
                        # --- THAY ĐỔI: Reset PriorityQueue ---
						self.cacheBuffer = queue.PriorityQueue(maxsize=1000)
                        # -------------------------------------
						self.state = self.READY
						self.openRtpPort() 
					elif self.requestSent == self.PLAY:
						self.state = self.PLAYING
					elif self.requestSent == self.PAUSE:
						self.state = self.READY
						self.playEvent.set()
					elif self.requestSent == self.TEARDOWN:
						self.state = self.INIT
						self.teardownAcked = 1 
	
	def openRtpPort(self):
		"""Open RTP socket binded to a specified port."""
		self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		self.rtpSocket.settimeout(0.5)
		try:
			self.rtpSocket.bind(("", self.rtpPort))
		except:
			tkMessageBox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtpPort)

	def handler(self):
		"""Handler on explicitly closing the GUI window."""
		self.pauseMovie()
		if tkMessageBox.askokcancel("Quit?", "Are you sure you want to quit?"):
            # --- THAY ĐỔI: Xóa queue ---
			self.cacheBuffer = queue.PriorityQueue(maxsize=1000)
			self.isBufferPlaying = False
            # ---------------------------
			self.sendRtspRequest(self.TEARDOWN)
			self.master.destroy() 
		else: 
			self.playMovie()
	
	def playMovieFromBuffer(self):
		"""Lấy frame từ PriorityQueue và hiển thị."""
		if self.state == self.PLAYING:
            
				if self.cacheBuffer.qsize() > 0:
					_, data = self.cacheBuffer.get()
                
					self.updateMovie(self.writeFrame(data))
            
				self.master.after(50, self.playMovieFromBuffer)
		else:
			self.isBufferPlaying = False

	def updateGUI(self):
		"""Cập nhật giao diện (Thanh Cache và Progress) liên tục."""
		
		self.progressScale.set(self.frameNbr)
		
		current_buffer_size = self.cacheBuffer.qsize()

		fill_percent = current_buffer_size / self.BUFFER_THRESHOLD
		
		if fill_percent > 1.0: fill_percent = 1.0
		
		bar_width = 300 * fill_percent
		
		self.cacheCanvas.coords(self.cacheBar, 0, 0, bar_width, 20)
		
		if current_buffer_size < self.BUFFER_THRESHOLD: 
			self.cacheCanvas.itemconfig(self.cacheBar, fill='red')
		else:
			self.cacheCanvas.itemconfig(self.cacheBar, fill='green')

		self.master.after(200, self.updateGUI)