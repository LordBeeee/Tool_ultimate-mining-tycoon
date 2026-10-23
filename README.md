# Tool đào quặng Ultimate Mining Tycoon

Ứng dụng Windows đọc màn hình Roblox và gửi thao tác bàn phím/chuột. Tool không đọc bộ nhớ game hoặc gọi Remote của Roblox.

## Cài và chạy

1. Cài Python 3.12, các gói trong `requirements.txt` (`python -m pip install -r requirements.txt`) và [Tesseract OCR](https://tesseract-ocr.github.io/tessdoc/Installation.html) với dữ liệu tiếng Anh. Nếu Tesseract không nằm trong PATH, chọn `tesseract.exe` ở cuối cửa sổ tool.
2. Chạy `run.bat` hoặc `python main.py`. Giữ cửa sổ Roblox, độ phân giải và zoom camera ổn định.
3. Mở menu **Vehicle Spawner** trong Roblox, để thẻ xe hiện đầy đủ rồi bấm **Quét menu Spawn**. Tool đọc Capacity và nút Spawn, sau đó hỏi bạn xác nhận tên từng xe vì chữ trên nền 3D dễ bị OCR đọc sai. Xe không có nút Spawn sẽ không được thêm. Chọn xe; chọn `drill` cho xe khoan, `haul` cho xe chở quặng đào bằng cuốc. Có thể bấm **Spawn xe đã chọn** khi menu còn mở.
4. Trong Roblox, đưa chuột lên quặng để hiện tên rồi bấm **F7**. Trong ảnh vừa chụp, bấm vào quặng và xác nhận tên OCR đọc được. Quặng mới xuất hiện trong danh sách nhưng mặc định chưa chọn. Đánh dấu một hoặc nhiều loại cần đào và dùng **Xem thử nhận diện** để kiểm tra vùng tool sẽ nhắm tới. Khi game hiện tên quặng trong lúc tool mở, nó cũng tự thêm tên và mẫu màu. Bấm **F6** để học thêm mẫu thiên thạch.
5. Với mỗi xe, ghi tuyến **từ chỗ ngồi trong xe ở nhà máy đến cửa mỏ**: bấm nút **Ghi tuyến**, lái trong Roblox, rồi bấm lại để lưu. Ghi một **lượt xả**: bắt đầu ngồi trong xe tại nhà máy, xuống lấy quặng, đặt lên `Place Ore Here!`, quay lại và ngồi vào xe. Với xe `haul`, ghi thêm thao tác xuống đào cuốc và chuyển quặng lên xe. Ghi C4 nếu muốn tool tự phá thiên thạch; lần bấm chuột đầu tiên của thao tác này phải là điểm đặt C4 trên thiên thạch.
6. Ngồi trong xe đã chọn ở nhà máy, bấm **Chạy**. **F8** tạm dừng/tiếp tục; **F9** dừng và nhả mọi phím ngay.

Cấu hình lưu trong `settings.json`, nhật ký trong `bot.log`. Tool không chạy khi chưa chọn quặng hoặc chưa ghi tuyến và thao tác xả của xe.

## Giới hạn cần kiểm thử trong game

Mỏ là môi trường 3D thay đổi khi đào. Tool ghi và đảo ngược các thao tác lái để tìm đường về; nó dừng sau ba lần thử thoát kẹt. Nếu chưa thể về, nó đợi game dịch chuyển người và xe lên cửa mỏ khi hết giờ. Những đường có người chơi khác cản, thay đổi bố cục lớn hoặc thao tác xoay camera bằng chuột có thể khiến tuyến ghi không còn chính xác.

Video của bạn cung cấp một mẫu thiên thạch ban đầu và tín hiệu `VEHICLE FULL`. Các góc nhìn/ánh sáng khác cần học thêm mẫu. Số lượt xả được tính từ Capacity của xe và sức chứa ba lô bạn đặt; phải thử trực tiếp với từng xe trước khi để tool chạy lâu. Chưa thể xác nhận một vòng đào–về–xả thực tế chỉ bằng video đã quay.
