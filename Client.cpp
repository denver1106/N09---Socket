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

// =======================================================================
//  ENUM TRẠNG THÁI RTSP
// =======================================================================
enum RTSPState {
    INIT = 0,
    READY = 1,
    PLAYING = 2
};

// =======================================================================
//  CLASS RTSP CLIENT HELPER (đặt trong file cpp giống format mẫu)
// =======================================================================
class RTSPClientHelper {
public:
    CSocket* m_pRtspSocket;   // Socket TCP điều khiển RTSP
    CSocket  m_RtpSocket;     // Socket UDP nhận RTP

    int m_nState;   // trạng thái client: INIT, READY, PLAYING
    int m_nCSeq;    // sequence number
    int m_nRtpPort; //cổng

    CString m_szSessionId;  // id session
    CString m_szFileName;  // Têm file video

    RTSPClientHelper(CSocket* pSocket)
        : m_pRtspSocket(pSocket),
          m_nState(INIT),
          m_nCSeq(1),
          m_nRtpPort(25000),
          m_szFileName(_T("movie.Mjpeg"))
    {}

    // ===================================================================
    // Gửi RTSP Request
    // ===================================================================
    void SendRTSPRequest(CString method)
    {
        CString strRequest;

        // Header chung
        strRequest.Format(_T("%s %s RTSP/1.0\r\nCSeq: %d\r\n"), method, m_szFileName, m_nCSeq);

        // Header đặc thù
        if (method == _T("SETUP")) {
            CString strTransport;
            strTransport.Format(_T("Transport: RTP/UDP; client_port=%d\r\n"), m_nRtpPort);
            strRequest += strTransport;
        }
        else {
            if (!m_szSessionId.IsEmpty()) {
                CString strSession;
                strSession.Format(_T("Session: %s\r\n"), m_szSessionId);
                strRequest += strSession;
            }
        }

        strRequest += _T("\r\n");

        // Debug
        wcout << _T("[CLIENT SEND]:\n") << (LPCTSTR)strRequest << endl;

        // Gửi TCP, tăng sequence num
        m_pRtspSocket->Send(strRequest, strRequest.GetLength());
        m_nCSeq++;

        // Đọc response
        ParseServerResponse();
    }

    // ===================================================================
    // Phân tích phản hồi từ server
    // ===================================================================
    void ParseServerResponse()
    {
        char buffer[4096];
        int len = m_pRtspSocket->Receive(buffer, 4096);

        if (len > 0)
        {
            buffer[len] = '\0';
            CString strResponse(buffer);

            wcout << _T("[SERVER RESPONSE]:\n") << (LPCTSTR)strResponse << endl;

            // Nếu server trả 200 OK
            if (strResponse.Find(_T("200 OK")) != -1)
            {
                int idx = strResponse.Find(_T("Session: "));
                if (idx != -1)
                {
                    CString strTemp = strResponse.Mid(idx + 9);
                    int endIdx = strTemp.Find(_T("\r\n"));

                    if (endIdx != -1)
                    {
                        m_szSessionId = strTemp.Left(endIdx);
                        wcout << _T("=> Lay Session ID: ") 
                              << (LPCTSTR)m_szSessionId << endl;
                    }
                }
            }
        }
    }

    // ===================================================================
    // SETUP
    // ===================================================================
    void DoSetup()
    {
        if (m_nState == INIT)
        {
            if (m_RtpSocket.Create(m_nRtpPort, SOCK_DGRAM) == 0) {
                cout << "Loi tao socket UDP!" << endl;
                return;
            }

            int timeOut = 500;
            m_RtpSocket.SetSockOpt(SO_RCVTIMEO, &timeOut, sizeof(int), SOL_SOCKET);

            cout << "=> Tao UDP Socket tai port " << m_nRtpPort << endl;

            SendRTSPRequest(_T("SETUP"));

            if (!m_szSessionId.IsEmpty())
                m_nState = READY;
        }
        else {
            cout << "Loi: Chi SETUP khi o INIT." << endl;
        }
    }

    // ===================================================================
    // PLAY
    // ===================================================================
    void DoPlay()
    {
        if (m_nState == READY) {
            SendRTSPRequest(_T("PLAY"));
            m_nState = PLAYING;
            cout << "=> Playing video..." << endl;
        }
        else if (m_nState == PLAYING) {
            cout << "Loi: Dang PLAY." << endl;
        }
        else {
            cout << "Loi: Chua SETUP." << endl;
        }
    }

    // ===================================================================
    // PAUSE
    // ===================================================================
    void DoPause()
    {
        if (m_nState == PLAYING)
        {
            SendRTSPRequest(_T("PAUSE"));
            m_nState = READY;
        }
        else {
            cout << "Loi: Chi PAUSE khi PLAYING." << endl;
        }
    }

    // ===================================================================
    // TEARDOWN
    // ===================================================================
    void DoTeardown()
    {
        SendRTSPRequest(_T("TEARDOWN"));
        m_RtpSocket.Close();
        m_szSessionId = _T("");
        m_nState = INIT;

        cout << "=> Dong UDP & reset trang thai." << endl;
    }
};


// =======================================================================
//  HÀM MAIN – Format giống hệt Demo_Client.cpp
// =======================================================================

int _tmain(int argc, TCHAR* argv[], TCHAR* envp[])
{
    int nRetCode = 0;

    HMODULE hModule = ::GetModuleHandle(NULL);

    if (hModule != NULL)
    {
        // Init MFC
        if (!AfxWinInit(hModule, NULL, ::GetCommandLine(), 0))
        {
            _tprintf(_T("Fatal Error: MFC initialization failed\n"));
            nRetCode = 1;
        }
        else
        {
            // ===============================
            // Init Socket
            // ===============================
            if (!AfxSocketInit(NULL)) {
                cout << "Khong the khoi tao Socket Library" << endl;
                return FALSE;
            }

            CSocket client;
            client.Create();

            CString serverIP = _T("127.0.0.1");
            int     serverPort = 554;

            cout << "Dang ket noi toi Server " << serverIP << ":" << serverPort << endl;

            if (client.Connect(serverIP, serverPort) != 0)
            {
                cout << "Ket noi thanh cong!" << endl;

                RTSPClientHelper rtsp(&client);

                char cmdBuffer[100];

                // ===============================
                // Vòng lặp điều khiển
                // ===============================
                while (true)
                {
                    cout << "\n------------------------------------------------";
                    cout << "\nNhap lenh (setup/play/pause/teardown/exit): ";
                    cin.getline(cmdBuffer, 100);

                    CString cmd(cmdBuffer);
                    cmd.MakeLower();

                    if (cmd == "setup") rtsp.DoSetup();
                    else if (cmd == "play") rtsp.DoPlay();
                    else if (cmd == "pause") rtsp.DoPause();
                    else if (cmd == "teardown") rtsp.DoTeardown();
                    else if (cmd == "exit") {
                        if (rtsp.m_nState != INIT)
                            rtsp.DoTeardown();
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
                cout << "Khong the ket noi den Server! Ma loi: " << err << endl;
            }

            client.Close();
        }
    }
    else
    {
        _tprintf(_T("Fatal Error: GetModuleHandle failed\n"));
        nRetCode = 1;
    }

    return nRetCode;
}
