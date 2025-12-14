class VideoStream:
    def __init__(self, filename):
        self.filename = filename
        try:
            self.file = open(filename, 'rb')
        except:
            raise IOError
        self.frameNum = 0
        
    def nextFrame(self):
        """Get next frame."""
        data = bytearray()
        
        # 1. Tìm Header bắt đầu ảnh (0xFF 0xD8)
        while True:
            byte = self.file.read(1)
            if not byte: # Hết file
                return None
            
            if byte == b'\xFF':
                byte2 = self.file.read(1)
                if byte2 == b'\xD8':
                    # Đã tìm thấy Start Marker
                    data = bytearray(b'\xFF\xD8')
                    break
        
        # 2. Tìm Footer kết thúc ảnh (0xFF 0xD9)
        while True:
            byte = self.file.read(1)
            if not byte: # Hết file hoặc file lỗi
                return None
                
            data += byte
            
            # Kiểm tra 2 byte cuối có phải FF D9 không
            if len(data) >= 2 and data[-2:] == b'\xFF\xD9':
                self.frameNum += 1
                return bytes(data)

    def frameNbr(self):
        """Get frame number."""
        return self.frameNum
