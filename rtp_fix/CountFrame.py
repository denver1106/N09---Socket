filename = "movie2.mjpeg"

def count_frames(file_path):
    count = 0
    try:
        with open(file_path, 'rb') as f:
            # Đọc toàn bộ file vào bộ nhớ
            data = f.read()
            # Đếm số lần xuất hiện của marker bắt đầu ảnh JPEG (0xFF 0xD8)
            count = data.count(b'\xff\xd8')
            print(f"Tổng số frame trong {file_path} là: {count}")
    except FileNotFoundError:
        print("Không tìm thấy file!")

count_frames(filename)