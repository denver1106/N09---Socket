// Client.cpp : Defines the entry point for the console application.
//

#include "stdafx.h"
#include "Client.h"
#include "afxsock.h"
#include <iostream>
#include <string>

#ifdef _DEBUG
#define new DEBUG_NEW
#endif

// The one and only application object
CWinApp theApp;

using namespace std;

// --- ĐỊNH NGHĨA CÁC TRẠNG THÁI RTSP ---
enum RTSPState {
	INIT = 0,
	READY = 1,
	PLAYING = 2
};

// --- CLASS HỖ TRỢ XỬ LÝ RTSP (Nằm gọn trong file cpp) ---
class RTSPClientHelper {
public:
	CSocket* m_pRtspSocket; // Con trỏ tới Socket TCP đã kết nối trong main
	CSocket  m_RtpSocket;   // Socket UDP nhận dữ liệu (tự quản lý)
	
	int m_nState;
	int m_nCSeq;
	int m_nRtpPort;
	CString m_szSessionId;
	CString m_szFileName;

	RTSPClientHelper(CSocket* pSocket) {
		m_pRtspSocket = pSocket;
		m_nState = INIT;
		m_nCSeq = 1;
		m_nRtpPort = 25000;         // Port nhận UDP mặc định
		m_szFileName = _T("movie.Mjpeg"); // Tên file video
	}

	// Hàm gửi Request và nhận Response chung
	void SendRTSPRequest(CString method) {
		CString strRequest;

		// 1. Tạo Header cơ bản
		strRequest.Format(_T("%s %s RTSP/1.0\r\nCSeq: %d\r\n"), method, m_szFileName, m_nCSeq);

		// 2. Xử lý Header đặc thù
		if (method == _T("SETUP")) {
			CString strTransport;
			strTransport.Format(_T("Transport: RTP/UDP; client_port=%d\r\n"), m_nRtpPort);
			strRequest += strTransport;
		}
		else {
			// PLAY, PAUSE, TEARDOWN cần Session ID
			if (!m_szSessionId.IsEmpty()) {
				CString strSession;
				strSession.Format(_T("Session: %s\r\n"), m_szSessionId);
				strRequest += strSession;
			}
		}

		// Kết thúc Header
		strRequest += _T("\r\n");

		// Gửi đi (In ra màn hình để debug)
		wcout << _T("[CLIENT SEND]:\n") << (LPCTSTR)strRequest << endl;
		m_pRtspSocket->Send(strRequest, strRequest.GetLength());

		// Tăng CSeq
		m_nCSeq++;

		// Đọc phản hồi ngay lập tức
		ParseServerResponse();
	}

	// Hàm phân tích phản hồi từ Server
	void ParseServerResponse() {
		char buffer[4096];
		int len = m_pRtspSocket->Receive(buffer, 4096);
		if (len > 0) {
			buffer[len] = '\0';
			CString strResponse(buffer);
			
			// In phản hồi ra màn hình
			wcout << _T("[SERVER RESPONSE]:\n") << (LPCTSTR)strResponse << endl;

			// Nếu thành công 200 OK
			if (strResponse.Find(_T("200 OK")) != -1) {
				// Tìm và lưu Session ID
				int idx = strResponse.Find(_T("Session: "));
				if (idx != -1) {
					CString strTemp = strResponse.Mid(idx + 9);
					int endIdx = strTemp.Find(_T("\r\n"));
					if (endIdx != -1) {
						m_szSessionId = strTemp.Left(endIdx);
						wcout << _T("=> Da lay duoc Session ID: ") << (LPCTSTR)m_szSessionId << endl;
					}
				}
			}
		}
	}

	// --- CÁC HÀM XỬ LÝ LỆNH ---

	void DoSetup() {
		if (m_nState == INIT) {
			// 1. Tạo Socket UDP
			if (m_RtpSocket.Create(m_nRtpPort, SOCK_DGRAM) == 0) {
				cout << "Loi tao socket UDP!" << endl;
				return;
			}
			// 2. Set Timeout 0.5s (500ms)
			int timeOut = 500;
			m_RtpSocket.SetSockOpt(SO_RCVTIMEO, &timeOut, sizeof(int), SOL_SOCKET);
			
			cout << "=> Da tao UDP Socket tai port " << m_nRtpPort << " (Timeout 0.5s)" << endl;

			// 3. Gửi lệnh
			SendRTSPRequest(_T("SETUP"));

			// 4. Đổi trạng thái
			if (!m_szSessionId.IsEmpty()) m_nState = READY;
		} else {
			cout << "Loi: Chi co the SETUP khi o trang thai INIT." << endl;
		}
	}

	void DoPlay() {
		if (m_nState == READY) {
			SendRTSPRequest(_T("PLAY"));
			m_nState = PLAYING;
			cout << "=> Dang choi video (Gia lap nhan RTP)..." << endl;
		} else if (m_nState == PLAYING) {
			cout << "Loi: Dang PLAY roi." << endl;
		} else {
			cout << "Loi: Can SETUP truoc." << endl;
		}
	}

	void DoPause() {
		if (m_nState == PLAYING) {
			SendRTSPRequest(_T("PAUSE"));
			m_nState = READY;
		} else {
			cout << "Loi: Chi co thể PAUSE khi đang PLAYING." << endl;
		}
	}

	void DoTeardown() {
		SendRTSPRequest(_T("TEARDOWN"));
		m_RtpSocket.Close();
		m_szSessionId = _T("");
		m_nState = INIT;
		cout << "=> Da dong ket noi UDP va reset trang thai." << endl;
	}
};

// --- HÀM MAIN ---

int _tmain(int argc, TCHAR* argv[], TCHAR* envp[])
{
	int nRetCode = 0;

	// initialize MFC and print and error on failure
	if (!AfxWinInit(::GetModuleHandle(NULL), NULL, ::GetCommandLine(), 0))
	{
		_tprintf(_T("Fatal Error: MFC initialization failed\n"));
		nRetCode = 1;
	}
	else
	{
		// Khoi tao Thu vien Socket
		if( AfxSocketInit() == FALSE)
		{ 
			cout << "Khong the khoi tao Socket Library";
			return FALSE; 
		}

		// Tao socket TCP de dieu khien RTSP
		CSocket ClientSocket;
		ClientSocket.Create();

		// Ket noi den Server
		// Luu y: Port RTSP mac dinh la 554, nhung bai lab co the dung 1234 hoac port khac
		// Ban hay doi so 554 duoi day thanh port ma Server cua ban dang mo (vd: 1234)
		int serverPort = 554; 
		CString serverIP = _T("127.0.0.1");

		cout << "Dang ket noi toi Server " << serverIP << ":" << serverPort << "..." << endl;

		if(ClientSocket.Connect(serverIP, serverPort) != 0)
		{
			cout << "Ket noi toi Server thanh cong !!!" << endl << endl;
			
			// Khoi tao Helper de xu ly RTSP logic
			RTSPClientHelper rtspClient(&ClientSocket);

			char cmdBuffer[100];
			
			// Vong lap dieu khien (Thay vi bam nut, ta go lenh)
			while (true)
			{
				cout << "\n------------------------------------------------";
				cout << "\nNhap lenh (setup, play, pause, teardown, exit): ";
				cin.getline(cmdBuffer, 100);

				CString cmd(cmdBuffer);
				cmd.MakeLower(); // Chuyen ve chu thuong de so sanh

				if (cmd == "setup") {
					rtspClient.DoSetup();
				}
				else if (cmd == "play") {
					rtspClient.DoPlay();
				}
				else if (cmd == "pause") {
					rtspClient.DoPause();
				}
				else if (cmd == "teardown") {
					rtspClient.DoTeardown();
				}
				else if (cmd == "exit") {
					// Gui teardown truoc khi thoat cho lich su
					if(rtspClient.m_nState != INIT) rtspClient.DoTeardown();
					break;
				}
				else {
					cout << "Lenh khong hop le!" << endl;
				}
			}
		}
		else
		{
			int err = GetLastError();
			cout << "Khong the ket noi den Server !!! Ma loi: " << err << endl;
			cout << "Luu y: Kiem tra lai Port va IP cua Server." << endl;
		}

		// Dong ket noi TCP
		ClientSocket.Close();
	}

	return nRetCode;
}