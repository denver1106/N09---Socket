class VideoStream:
	def __init__(self, filename):
		self.filename = filename
		try:
			self.file = open(filename, 'rb')
		except:
			raise IOError
		self.frameNum = 0
		# [THÊM] Buffer để chứa dữ liệu đọc từ file phục vụ việc tìm kiếm marker ảnh
		self.buffer = b''
		
	def nextFrame(self):
		"""Get next frame."""
		
		# [THÊM] Logic mới: Hỗ trợ cả file bài lab (header 5 byte) và file HD chuẩn (Start/End marker)
		# Thay vì đọc 5 byte độ dài, ta quét tìm marker bắt đầu (0xFFD8) và kết thúc (0xFFD9) của JPEG
		
		# 1. Tìm điểm bắt đầu của ảnh (SOI: 0xFF 0xD8)
		while True:
			# Tìm chuỗi byte start trong buffer
			start_index = self.buffer.find(b'\xff\xd8')
			
			if start_index != -1:
				# Nếu tìm thấy, cắt bỏ phần rác phía trước (bao gồm cả header 5-byte cũ nếu có)
				self.buffer = self.buffer[start_index:]
				break
			
			# Nếu chưa thấy, đọc thêm dữ liệu từ file (4KB mỗi lần)
			data = self.file.read(4096)
			if not data:
				return None # Hết file
			self.buffer += data

		# 2. Tìm điểm kết thúc của ảnh (EOI: 0xFF 0xD9)
		while True:
			# Tìm chuỗi byte end. Bắt đầu tìm từ vị trí thứ 2 để tránh trùng lặp
			end_index = self.buffer.find(b'\xff\xd9', 2)
			
			if end_index != -1:
				# Cộng thêm 2 để lấy luôn cả 2 byte FFD9
				end_index += 2
				
				# Trích xuất toàn bộ dữ liệu của 1 frame
				frame_data = self.buffer[:end_index]
				
				# Cập nhật buffer: Xóa frame đã lấy, giữ lại phần còn dư cho lần sau
				self.buffer = self.buffer[end_index:]
				
				self.frameNum += 1
				return frame_data
			
			# Nếu chưa thấy EOI, tiếp tục đọc thêm từ file
			data = self.file.read(4096)
			if not data:
				return None
			self.buffer += data

		# --- [ĐOẠN CODE CŨ DƯỚI ĐÂY ĐÃ ĐƯỢC THAY THẾ BỞI LOGIC TRÊN ĐỂ HỖ TRỢ HD] ---
		# data = self.file.read(5) # Get the framelength from the first 5 bits
		# if data: 
		# 	framelength = int(data)
							
		# 	# Read the current frame
		# 	data = self.file.read(framelength)
		# 	self.frameNum += 1
		# return data
		
	def frameNbr(self):
		"""Get frame number."""
		return self.frameNum