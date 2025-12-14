from tkinter import *
import tkinter.messagebox
from tkinter import messagebox as tkMessageBox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os

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
		self.frameBuffer = b"" # Thêm dòng này để chứa dữ liệu phân mảnh
		# --- SỬA ĐỔI ---
		self.cacheBuffer = []        # Dùng List để làm bộ đệm
		self.BUFFER_THRESHOLD = 60   # Ngưỡng đệm (60 frame)
		self.isBufferPlaying = False # Cờ trạng thái phát
		# ---------------
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
		# Giả sử video dài khoảng 500 frame (hoặc bạn có thể tăng lên nếu video dài hơn)
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
		self.master.destroy() # Close the gui window
		# os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT) # Delete the cache image from video
		try:
			os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT) 
		except OSError:
			# Nếu file không tồn tại (do chưa play được frame nào), bỏ qua lỗi
			pass

	def pauseMovie(self):
		"""Pause button handler."""
		if self.state == self.PLAYING:
			self.sendRtspRequest(self.PAUSE)
	
	def playMovie(self):
		"""Play button handler."""
		if self.state == self.READY:
			# Create a new thread to listen for RTP packets
			threading.Thread(target=self.listenRtp).start()
			self.playEvent = threading.Event()
			self.playEvent.clear()
			self.sendRtspRequest(self.PLAY)
	
	def listenRtp(self):		
		"""Listen for RTP packets."""
		while True:
			try:
				data = self.rtpSocket.recv(20480)
				if data:
					rtpPacket = RtpPacket()
					rtpPacket.decode(data)
					
					# Lấy dữ liệu payload và thêm vào buffer hiện tại
				self.frameBuffer += rtpPacket.getPayload()

				# Kiểm tra xem đây có phải gói cuối cùng của khung hình không (Marker = 1)
				if rtpPacket.getMarker() == 1:
					currFrameNbr = rtpPacket.seqNum()
					# print("Current Seq Num: " + str(currFrameNbr))

					# Chỉ hiển thị nếu đây là frame mới (bỏ logic check > frameNbr nếu muốn đơn giản, 
                    # nhưng tốt nhất giữ lại để tránh hiển thị frame cũ đến muộn)
					if currFrameNbr > self.frameNbr: 
						self.frameNbr = currFrameNbr
                        
                        # --- SỬA ĐỔI Ở ĐÂY ---
                        # Thay vì gọi self.updateMovie() ngay, ta thêm vào cuối danh sách
						self.cacheBuffer.append(self.frameBuffer)
                        
                        # Kiểm tra xem kho đã đủ hàng chưa (đủ 20 frame) và đã bắt đầu phát chưa
						if not self.isBufferPlaying and len(self.cacheBuffer) >= self.BUFFER_THRESHOLD:
                            # Nếu đủ rồi thì bật cờ và kích hoạt hàm phát (Consumer)
							self.isBufferPlaying = True
							self.playMovieFromBuffer()
                        # ---------------------

					# Xóa buffer sau khi đã xử lý xong khung hình (dù có hiển thị hay không)
					self.frameBuffer = b""
			except:
				# Stop listening upon requesting PAUSE or TEARDOWN
				if self.playEvent.isSet(): 
					break
				
				# Upon receiving ACK for TEARDOWN request,
				# close the RTP socket
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
		#-------------
		# TO COMPLETE
		#-------------
		
		# Setup request
		if requestCode == self.SETUP and self.state == self.INIT:
			threading.Thread(target=self.recvRtspReply).start()
			# Update RTSP sequence number.
			# ...
			# --- CẬP NHẬT: RESET SẠCH SẼ BIẾN CŨ TẠI ĐÂY ---
			self.rtspSeq = 0
			self.sessionId = 0          # Reset Session ID cũ
			self.requestSent = -1
			self.teardownAcked = 0      # <--- QUAN TRỌNG NHẤT: Đặt lại cờ này về 0
			self.frameNbr = 0
			self.buffer = []            # Xóa buffer cũ
			self.packetLossCount = 0
			self.totalBytes = 0
            # -----------------------------------------------
			self.rtspSeq += 1 

			# Write the RTSP request to be sent.
			# request = ...
			request = "SETUP " + str(self.fileName) + " RTSP/1.0\n" + \
					  "CSeq: " + str(self.rtspSeq) + "\n" + \
					  "Transport: RTP/UDP; client_port= " + str(self.rtpPort)
			# Keep track of the sent request.
			# self.requestSent = ...
			self.requestSent = self.SETUP
		
		# Play request
		elif requestCode == self.PLAY and self.state == self.READY:
			# Update RTSP sequence number.
			# ...
			self.rtspSeq += 1
			# Write the RTSP request to be sent.
			# request = ...
			request = "PLAY " + str(self.fileName) + " RTSP/1.0\n" + \
					  "CSeq: " + str(self.rtspSeq) + "\n" + \
					  "Session: " + str(self.sessionId)
			# Keep track of the sent request.
			# self.requestSent = ...
			self.requestSent = self.PLAY
		
		# Pause request
		elif requestCode == self.PAUSE and self.state == self.PLAYING:
			# Update RTSP sequence number.
			# ...
			self.rtspSeq += 1
			# Write the RTSP request to be sent.
			# request = ...
			request = "PAUSE " + str(self.fileName) + " RTSP/1.0\n" + \
					  "CSeq: " + str(self.rtspSeq) + "\n" + \
					  "Session: " + str(self.sessionId)
			# Keep track of the sent request.
			# self.requestSent = ...
			self.requestSent = self.PAUSE
			
		# Teardown request
		elif requestCode == self.TEARDOWN and not self.state == self.INIT:
			# Update RTSP sequence number.
			# ...
			self.rtspSeq += 1
			# Write the RTSP request to be sent.
			# request = ...
			request = "TEARDOWN " + str(self.fileName) + " RTSP/1.0\n" + \
					  "CSeq: " + str(self.rtspSeq) + "\n" + \
					  "Session: " + str(self.sessionId)
			# Keep track of the sent request.
			# self.requestSent = ...
			self.requestSent = self.TEARDOWN
		else:
			return
		
		# Send the RTSP request using rtspSocket.
		# ...
		self.rtspSocket.send(request.encode('utf-8'))
		
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
						#-------------
						# TO COMPLETE
						#-------------
						# Update RTSP state.
						# self.state = ...
						self.cacheBuffer = []
						self.state = self.READY
						
						# Open RTP port.
						self.openRtpPort() 
					elif self.requestSent == self.PLAY:
						# self.state = ...
						self.state = self.PLAYING
					elif self.requestSent == self.PAUSE:
						# self.state = ...
						self.state = self.READY
						
						# The play thread exits. A new thread is created on resume.
						self.playEvent.set()
					elif self.requestSent == self.TEARDOWN:
						# self.state = ...
						self.state = self.INIT
						
						# Flag the teardownAcked to close the socket.
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
            # --- THÊM DÒNG NÀY ---
			self.cacheBuffer = [] # Xóa sạch bộ đệm
			self.isBufferPlaying = False
            # ---------------------
			self.sendRtspRequest(self.TEARDOWN)
			self.master.destroy() # Close the gui window
		else: # When the user presses cancel, resume playing.
			self.playMovie()
	
	def playMovieFromBuffer(self):
		"""Lấy frame từ bộ đệm List và hiển thị."""
        # Chỉ chạy khi trạng thái là PLAYING
		if self.state == self.PLAYING:
            
            # Kiểm tra xem trong kho còn hàng không
				if len(self.cacheBuffer) > 0:
                	# Lấy phần tử đầu tiên ra khỏi danh sách (FIFO) và xóa nó khỏi kho
					data = self.cacheBuffer.pop(0)
                
                	# Ghi dữ liệu ra file ảnh và hiển thị lên giao diện
					self.updateMovie(self.writeFrame(data))
            
            	# Lập lịch để tự gọi lại chính hàm này sau 50ms (tạo vòng lặp hiển thị)
				self.master.after(50, self.playMovieFromBuffer)
		else:
            # Nếu người dùng bấm PAUSE hoặc TEARDOWN thì dừng vòng lặp
			self.isBufferPlaying = False
	def updateGUI(self):
		"""Cập nhật giao diện (Thanh Cache và Progress) liên tục."""
		
		# 1. Cập nhật Progress Bar theo số frame hiện tại
		self.progressScale.set(self.frameNbr)
		
		# 2. Cập nhật Cache Bar
		# Tính phần trăm bộ đệm (Hiện tại / Ngưỡng)
		current_buffer_size = len(self.cacheBuffer)
		fill_percent = current_buffer_size / self.BUFFER_THRESHOLD
		
		# Giới hạn max là 100% (để không vẽ tràn ra ngoài)
		if fill_percent > 1.0: fill_percent = 1.0
		
		# Tính độ rộng của thanh màu (Canvas rộng 300px)
		bar_width = 300 * fill_percent
		
		# Vẽ lại hình chữ nhật
		self.cacheCanvas.coords(self.cacheBar, 0, 0, bar_width, 20)
		
		# logic: Nếu chưa đầy 100% thì hiện màu đỏ, đầy rồi mới xanh
		if current_buffer_size < self.BUFFER_THRESHOLD: 
			self.cacheCanvas.itemconfig(self.cacheBar, fill='red')
		else:
			self.cacheCanvas.itemconfig(self.cacheBar, fill='green')
		# --------------------

		self.master.after(200, self.updateGUI)