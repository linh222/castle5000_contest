# Technical note: Hệ thống truy vấn ảnh (retrieval) cho lớp học, kết nối DRES

Oct 6, 2026 · @Hanh Nguyen

## 1. Mục tiêu, ràng buộc và giả định

Retrieval system là ứng dụng web cho sinh viên nhập truy vấn, xem kết quả trong 5.000 ảnh và submit một ảnh lên DRES để chấm điểm. Note này mô tả những gì cần có; note DRES kèm theo mô tả phía server chấm điểm và hợp đồng submit.

**Ràng buộc đã chốt**

- Khoảng 40 sinh viên dùng đồng thời, truy cập công khai qua trình duyệt.
- Chạy chung một VPS với DRES (4 vCPU, 8 GB RAM), trong Docker Compose, sau Caddy (HTTPS).
- Cổng nội bộ của retrieval là 5000 (khớp `Caddyfile` trong báo cáo kế hoạch); sinh viên chỉ đi qua Caddy.
- Embedding và index tính sẵn offline; server chỉ nạp vào RAM khi khởi động.
- Backend gọi DRES qua địa chỉ nội bộ `http://dres:8080`; trình duyệt không gọi DRES trực tiếp.

**Giả định cần bạn xác nhận (chưa có thông tin về codebase hiện tại)**

- Backend Python (FastAPI) và frontend web đơn giản. Nếu bạn đã có hệ thống truy vấn, giữ nguyên stack đó và chỉ thêm các phần ở mục 4 và 6.
- Truy vấn là văn bản; mô hình CLIP (hoặc tương đương) mã hóa truy vấn trên CPU.
- Mỗi ảnh có một ID duy nhất, cố định, dùng làm `mediaItemName` khi submit lên DRES.

**Ngoài phạm vi**

- Huấn luyện hoặc tinh chỉnh mô hình.
- Giao diện admin riêng (admin dùng giao diện của DRES).

## 2. Kiến trúc đề xuất

Một container backend phục vụ cả API, ảnh và frontend tĩnh, để triển khai chỉ có một dịch vụ phía retrieval.

| Thành phần | Vai trò | Ghi chú |
| --- | --- | --- |
| Frontend | Đăng nhập, ô tìm kiếm, lưới kết quả, nút submit | Build thành file tĩnh, backend phục vụ |
| Backend (FastAPI, cổng 5000) | API tìm kiếm, phiên đăng nhập, gọi DRES | Một tiến trình, nạp index khi khởi động |
| Mô hình mã hóa truy vấn | Biến câu truy vấn thành vector | Chạy CPU, nạp một lần |
| Index FAISS + bảng ID | Tìm k ảnh gần nhất, ánh xạ vị trí sang ID ảnh | Nạp vào RAM, chỉ đọc |
| Kho ảnh | 5.000 ảnh gốc và thumbnail | Mount chỉ đọc, phục vụ qua backend hoặc Caddy |
| Client DRES | Đăng nhập và submit | Sinh từ OpenAPI spec của DRES |

**Cấu trúc repo gợi ý**

```
retrieval/
  backend/
    app/            # main.py, routes, dres_client.py, search.py, config.py
    tests/
    Dockerfile
  frontend/         # mã nguồn giao diện
  tools/
    build_index.py  # tính embedding và index offline
    check_ids.py    # so khớp ID với DRES
  data/             # index, bảng ID (không commit ảnh gốc)
  docker-compose.yml
```

## 3. Dữ liệu và index

Với 5.000 ảnh, một index phẳng (exact search) là đủ nhanh, không cần index xấp xỉ.

**Quy ước ID ảnh (quan trọng nhất)**

- Mỗi ảnh có một ID cố định, duy nhất. Đề xuất dùng đúng tên file làm ID, và thống nhất có kèm đuôi file hay không.
- ID này là giá trị gửi lên DRES trong `mediaItemName`, nên phải bằng đúng tên item mà DRES tạo khi quét thư mục ảnh (xem phần 6.3 của note DRES). Cách DRES đặt tên item cần được kiểm chứng trước khi chốt quy ước.
- Sau khi tạo media collection trong DRES, không đổi tên file hay ID.

**Pipeline offline (`tools/build_index.py`)**

1. Duyệt thư mục ảnh, sắp xếp theo tên để thứ tự ổn định.
2. Mã hóa từng ảnh bằng mô hình embedding đã chọn, theo lô; chuẩn hóa L2 vector.
3. Lưu ma trận embedding (`.npy`) và bảng ID theo cùng thứ tự (`ids.json`).
4. Dựng index FAISS phẳng theo tích vô hướng (`IndexFlatIP`) và ghi ra file.
5. Tạo thumbnail (ví dụ cạnh dài 320 px) để lưới kết quả tải nhanh; giữ ảnh gốc cho khi xem phóng to.
6. In thống kê: số ảnh, số ảnh lỗi, kích thước index. Dừng nếu số ảnh khác 5.000 ngoài dự kiến.

**Nạp khi khởi động**

- Backend đọc index, `ids.json` và mô hình vào RAM một lần, rồi mới báo sẵn sàng ở endpoint `/health`.
- Tìm kiếm là chỉ đọc nên nhiều request dùng chung index mà không cần khóa.

## 4. Backend API đề xuất

Backend chỉ cần sáu endpoint. Đường dẫn dưới đây là đề xuất của note này, không phải API của DRES.

| Endpoint | Mục đích | Ghi chú |
| --- | --- | --- |
| `POST /api/login` | Đăng nhập bằng tài khoản DRES | Backend gọi DRES login, tạo phiên cục bộ (cookie `HttpOnly`) |
| `POST /api/logout` | Kết thúc phiên | Xóa phiên cục bộ |
| `POST /api/search` | Tìm ảnh theo truy vấn | Cần đăng nhập, có rate limit |
| `GET /api/task` | Task hiện tại và thời gian còn lại | Proxy tới DRES, cache ngắn |
| `POST /api/submit` | Submit một ảnh lên DRES | Theo hợp đồng ở phần 6 |
| `GET /health` | Kiểm tra sẵn sàng | Trả 200 sau khi nạp xong index; cho Docker healthcheck |

Ảnh và thumbnail phục vụ qua `GET /images/{id}` và `GET /thumbs/{id}` (cần đăng nhập hoặc chỉ cho phép qua Referer của trang; chọn một cách).

**Ví dụ `POST /api/search`**

```json
// request
{ "query": "a red bus near a river", "k": 50 }

// response
{
  "results": [
    { "id": "img_00123.jpg", "score": 0.31, "thumb": "/thumbs/img_00123.jpg" }
  ],
  "took_ms": 180
}
```

**Quy tắc**

- Giới hạn `k` tối đa (ví dụ 100) và độ dài truy vấn tối đa (ví dụ 300 ký tự); trả `422` nếu vượt.
- Mã hóa truy vấn là phần nặng nhất; giữ nó trong một pool nhỏ hoặc hàng đợi để 40 request đồng thời không làm nghẽn CPU của DRES chạy cùng máy.
- Mọi lỗi trả JSON có `code` và `message` ngắn, để giao diện hiển thị được.

## 5. Frontend

Giao diện một trang, tối giản, chạy tốt trên Chrome, Firefox, Edge và điện thoại (DRES không hỗ trợ Safari, nên ghi chú này cho sinh viên).

**Màn hình**

1. **Đăng nhập:** tên đăng nhập và mật khẩu của DRES; hiện lỗi rõ khi sai.
2. **Tìm kiếm:** một ô nhập truy vấn, nút tìm, lưới thumbnail theo điểm giảm dần.
3. **Xem ảnh:** nhấn vào thumbnail để phóng to; nút Submit nằm ngay trong khung xem.
4. **Thanh trạng thái:** tên task hiện tại, đồng hồ đếm ngược (theo giờ server DRES), tên người dùng, nút đăng xuất.

**Hành vi cần có**

- Hộp xác nhận ngắn trước khi submit, vì mỗi submit có thể bị tính là sai và trừ điểm tùy cách chấm của template.
- Sau submit, hiện ngay kết quả chuẩn hóa (`correct`, `wrong`, `pending`, `rejected`) và đánh dấu ảnh đã gửi.
- Khi không có task đang chạy, vô hiệu ô tìm kiếm và nút submit, hiện "Chưa có task đang chạy".
- Giữ lại truy vấn và kết quả gần nhất khi tải lại trang.
- Lưới tải thumbnail lười (lazy), không tải ảnh gốc cho tới khi phóng to.

## 6. Tích hợp DRES

Hợp đồng đầy đủ (luồng, bảng mã phản hồi, endpoint v2) nằm ở phần 5 và 7 của note DRES; đây là phần việc phía retrieval.

**`dres_client.py`**

- Sinh client Python từ `doc/oas-client.json` của repo DRES, hoặc viết lớp mỏng bọc `requests`/`httpx` với đúng các endpoint v2 đã liệt kê. Không dùng endpoint v1 (`GET /api/v1/submit`, đã deprecated).
- Cấu hình bằng biến môi trường: `DRES_BASE_URL` (mặc định `http://dres:8080`), `DRES_EVALUATION_ID` (tùy chọn), thời gian chờ gọi DRES.
- Hàm chính: `login(username, password)`, `current_task(evaluation_id, session)`, `submit(evaluation_id, session, item_id)`, `server_time()`.

**Phiên đăng nhập**

- Sau `login`, lưu session token của DRES phía server, gắn với cookie `HttpOnly` của retrieval; không đưa token DRES xuống trình duyệt.
- Mật khẩu chỉ nằm trong bộ nhớ trong lúc gọi login, không ghi log, không lưu.
- Gặp `401` khi submit: thử đăng nhập lại một lần nếu còn thông tin phiên hợp lệ, nếu không yêu cầu đăng nhập lại.

**Submit**

- Body gồm một `answerSet` với một answer có `mediaItemName` = ID ảnh. Đọc tên field chính xác từ schema `ApiClientSubmission` trong spec rồi mới viết.
- Chuẩn hóa phản hồi theo bảng ở note DRES (`200`, `202`, `400`, `401`, `404`, `412`) thành `correct`/`wrong`/`pending`/`rejected`/`error`. Cách đọc verdict từ `SuccessfulSubmissionsStatus` cần xem trong spec.
- Không tự retry `POST` submit.

**Test bằng DRES giả (mock)**

- Viết một server giả trả các mã `200`, `202`, `401`, `404`, `412` để test không cần DRES thật; test tích hợp thật chạy ở phần 9.

## 7. Docker và triển khai

Một image cho backend (kèm frontend đã build), chạy chung `docker-compose.yml` với DRES và Caddy.

**Dockerfile (bản nháp, hướng dẫn)**

- Giai đoạn 1: build frontend thành file tĩnh.
- Giai đoạn 2: image Python slim, cài phụ thuộc đã khóa phiên bản (`requirements.txt`), copy backend và frontend tĩnh, chạy `uvicorn` ở cổng 5000.
- Cache mô hình embedding vào image hoặc volume để container không tải lại mỗi lần khởi động.
- `HEALTHCHECK` gọi `/health`; `restart: unless-stopped`.

**Biến môi trường**

| Biến | Ý nghĩa |
| --- | --- |
| `DRES_BASE_URL` | Địa chỉ nội bộ của DRES, mặc định `http://dres:8080` |
| `DRES_EVALUATION_ID` | Evaluation đang chạy (tùy chọn) |
| `INDEX_PATH`, `IDS_PATH` | Đường dẫn index FAISS và bảng ID |
| `IMAGES_DIR`, `THUMBS_DIR` | Thư mục ảnh và thumbnail |
| `SESSION_SECRET` | Khóa ký cookie phiên; đặt ngoài repo |
| `MAX_K`, `RATE_LIMIT_PER_MIN` | Giới hạn kết quả và tần suất tìm kiếm |

**Compose (phần retrieval, bản nháp)**

```yaml
services:
  retrieval:
    build: ./retrieval
    restart: unless-stopped
    environment:
      DRES_BASE_URL: http://dres:8080
    volumes:
      - ./retrieval-data:/app/data:ro
      - ./images:/app/images:ro
    expose:
      - "5000"
```

Caddy chuyển `search.tenmien.edu.vn` tới `retrieval:5000` như trong báo cáo kế hoạch. Chỉ Caddy publish cổng 80/443 ra ngoài.

## 8. Hiệu năng và bảo mật

Retrieval và DRES chia nhau 4 vCPU và 8 GB RAM, nên mục tiêu là retrieval không bao giờ làm DRES chậm lại trong lúc nhận submit.

**Hiệu năng**

- Đo thời gian mã hóa một truy vấn trên CPU của VPS thật trước khi chốt cấu hình; nếu quá chậm, hạ kích thước mô hình hoặc nâng VPS tạm thời.
- Giới hạn số truy vấn đang mã hóa cùng lúc (pool nhỏ hoặc hàng đợi); phần còn lại chờ, thay vì tranh CPU.
- Cache kết quả theo (truy vấn, k) trong bộ nhớ, có giới hạn kích thước; nhiều sinh viên hay gõ cùng một truy vấn khi task giống nhau.
- Thumbnail nhỏ, có `Cache-Control` dài để trình duyệt giữ lại.
- Giới hạn bộ nhớ container (`mem_limit`) để một lỗi rò rỉ không làm chết cả VPS.

**Bảo mật**

- Cookie phiên `HttpOnly`, `Secure`, `SameSite=Lax`; khóa ký đặt ngoài repo.
- Rate limit theo user cho `/api/search` và `/api/submit`; giới hạn thêm ở Caddy nếu cần.
- Chỉ nhận ID ảnh nằm trong bảng ID; từ chối mọi ID khác trước khi gọi DRES (chống gửi giá trị tùy ý).
- Không đưa token DRES, mật khẩu hay khóa phiên vào log hoặc phản hồi API.
- Không chạy container bằng root; không mở cổng 5000 ra host.
- Kiểm tra bản quyền và quyền riêng tư của 5.000 ảnh trước khi cho truy cập công khai.

## 9. Kiểm thử

Bốn lớp kiểm thử, từ nhanh tới sát thực tế; chỉ lớp cuối cần VPS và domain thật.

| Lớp | Nội dung | Điều kiện đạt |
| --- | --- | --- |
| Unit | `search.py` (top-k đúng thứ tự, giới hạn `k`), `dres_client.py` với DRES giả (đủ mã `200`, `202`, `401`, `404`, `412`) | Tất cả pass, không cần mạng |
| Dữ liệu | `tools/check_ids.py`: ID trong index so với item trong DRES | Không thiếu, không thừa, không lệch chữ hoa/thường |
| Tích hợp | Chạy DRES thật bằng Docker, một user, một task: login, search, submit, thấy điểm trên DRES | Điểm hiển thị đúng ở giao diện admin |
| Tải | 40–50 user đồng thời: login, search, submit (k6 hoặc Locust) | Search p95 và submit p95 chấp nhận được; không lỗi `5xx`; RAM trong giới hạn |

**Dry-run**

- Chạy một task thử với trợ giảng trên domain thật và mạng ngoài trường, trình duyệt Chrome, Firefox và điện thoại.
- Kiểm tra các trường hợp biên: hết giờ task, nhấn submit hai lần, session hết hạn giữa chừng, đăng nhập sai mật khẩu, mất kết nối tới DRES.

**Ngưỡng cần chốt**

Con số "chấp nhận được" cho độ trễ chưa được đặt; đề xuất đo ở lần chạy thử đầu tiên rồi chốt cùng bạn (ví dụ search dưới 2 giây ở p95 khi 40 người dùng đồng thời).

## 10. Việc cần làm cho Claude Code

Làm theo thứ tự; mục 1 quyết định cách làm các mục sau, nên trả lời các câu hỏi mở ở phần 11 trước.

- [ ] Xác định hiện trạng: đã có codebase retrieval chưa; nếu có, đọc và ghi lại stack, cách mã hóa truy vấn, cách tải ảnh
- [ ] Chốt quy ước ID ảnh cùng note DRES (tên file có đuôi hay không)
- [ ] Viết `tools/build_index.py`: embedding, index FAISS, `ids.json`, thumbnail, thống kê
- [ ] Viết `search.py` nạp index vào RAM, test top-k
- [ ] Dựng backend: `/health`, `/api/login`, `/api/logout`, `/api/search`, `/images`, `/thumbs`
- [ ] Viết `dres_client.py` và DRES giả để test, rồi `/api/task` và `/api/submit`
- [ ] Viết frontend: đăng nhập, tìm kiếm, lưới, phóng to, submit, đồng hồ task
- [ ] Viết `tools/check_ids.py` và chạy trên collection DRES thật
- [ ] Viết Dockerfile, healthcheck, compose chung với DRES và Caddy
- [ ] Thêm rate limit, cache kết quả, giới hạn bộ nhớ
- [ ] Viết test tích hợp với DRES thật bằng Docker
- [ ] Viết kịch bản load test 40–50 user và chạy trên VPS thật
- [ ] Dry-run với trợ giảng, ghi lại lỗi và sửa
- [ ] Viết tài liệu một trang cho sinh viên

## 11. Câu hỏi mở

Các câu hỏi dưới đây cần bạn trả lời (hoặc Claude Code kiểm chứng) trước khi code; các câu đầu quyết định nhiều nhất.

- Bạn đã có codebase retrieval (ví dụ một hệ thống đã dùng trước đây) hay dựng mới? Nếu có, đường dẫn repo và stack là gì?
- Truy vấn chỉ là văn bản, hay có thêm ảnh mẫu hoặc truy vấn theo bước (nhiều lượt)?
- Mô hình embedding nào (CLIP biến thể nào), và ảnh có phải ảnh thường hay ảnh lifelog? Điều này ảnh hưởng độ trễ và quyền riêng tư.
- Bộ 5.000 ảnh đã có tên file ổn định chưa, hay cần đặt lại tên trước khi tạo collection DRES?
- Mỗi sinh viên một tài khoản hay mỗi nhóm một tài khoản (ảnh hưởng chống nhấn submit trùng giữa các thành viên)?
- Task chấm điểm thế nào (một ảnh đúng, nhiều ảnh, phạt submit sai)? Điều này quyết định hộp xác nhận trước khi submit.
- Ngưỡng độ trễ chấp nhận được khi 40 người tìm cùng lúc.
