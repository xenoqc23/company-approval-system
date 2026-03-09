import streamlit as st
import pandas as pd
import os
from datetime import datetime

# --- 1~4. 기존 데이터 저장 및 상태 변경 함수 ---
DATA_FILE = "approval_data.csv"

def load_data():
    if os.path.exists(DATA_FILE):
        return pd.read_csv(DATA_FILE)
    else:
        return pd.DataFrame(columns=["문서번호", "구분", "제목", "기안자", "상태", "기안일"])

def save_data(doc_type, title, author):
    df = load_data()
    doc_no = f"DOC-{datetime.now().strftime('%y%m%d-%H%M%S')}"
    today = datetime.now().strftime('%Y-%m-%d')
    new_data = pd.DataFrame([{"문서번호": doc_no, "구분": doc_type, "제목": title, "기안자": author, "상태": "결재대기", "기안일": today}])
    df = pd.concat([df, new_data], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)

def update_status(doc_no, new_status):
    df = load_data()
    df.loc[df['문서번호'] == doc_no, '상태'] = new_status
    df.to_csv(DATA_FILE, index=False)

# ==========================================

# 5. 세션 상태 관리 (권한 저장 기능 추가)
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'page' not in st.session_state:
    st.session_state['page'] = 'dashboard'
if 'current_user' not in st.session_state:
    st.session_state['current_user'] = ""
if 'role' not in st.session_state: # ★ 새로운 꼬리표(권한) 저장 공간 ★
    st.session_state['role'] = ""

# 6. ★수정됨★ 로그인 화면 (계정 분리)
def login_page():
    st.title("🏢 사내 전자결재 시스템")
    st.markdown("---")
    st.info("💡 **테스트 계정 안내**\n- 일반 직원: ID `user` / PW `1234`\n- 관리자(팀장): ID `admin` / PW `1234`")
    
    username = st.text_input("아이디")
    password = st.text_input("비밀번호", type="password")
    
    if st.button("로그인", type="primary", use_container_width=True):
        # 1. 관리자 로그인
        if username == "admin" and password == "1234":
            st.session_state['logged_in'] = True
            st.session_state['current_user'] = "김팀장"
            st.session_state['role'] = "manager" # 관리자 권한 부여
            st.session_state['page'] = 'dashboard'
            st.rerun()
        # 2. 일반 직원 로그인
        elif username == "user" and password == "1234":
            st.session_state['logged_in'] = True
            st.session_state['current_user'] = "이대리"
            st.session_state['role'] = "employee" # 일반 직원 권한 부여
            st.session_state['page'] = 'dashboard'
            st.rerun()
        else:
            st.error("아이디 또는 비밀번호가 틀렸습니다.")

# 7. ★수정됨★ 사이드바 구성 (권한별 메뉴 노출)
def sidebar_menu():
    st.sidebar.title("메뉴")
    
    # 내 권한에 따라 뱃지 색상 다르게 표시
    if st.session_state['role'] == 'manager':
        st.sidebar.success(f"👨‍💼 **{st.session_state['current_user']}** (관리자)")
    else:
        st.sidebar.info(f"👩‍💼 **{st.session_state['current_user']}** (일반 직원)")
        
    st.sidebar.markdown("---")
    
    # 공통 메뉴
    if st.sidebar.button("🏠 홈 (대시보드)", use_container_width=True):
        st.session_state['page'] = 'dashboard'
        st.rerun()
        
    # 직원 전용 메뉴
    if st.session_state['role'] == 'employee':
        if st.sidebar.button("📝 새 결재 기안", use_container_width=True):
            st.session_state['page'] = 'new_document'
            st.rerun()
            
    # 관리자 전용 메뉴
    if st.session_state['role'] == 'manager':
        if st.sidebar.button("✅ 결재함 (승인/반려)", use_container_width=True):
            st.session_state['page'] = 'approval_box'
            st.rerun()
            
    # 공통 메뉴
    if st.sidebar.button("📄 결재 문서 열람", use_container_width=True):
        st.session_state['page'] = 'document_view'
        st.rerun()
    
    st.sidebar.markdown("---")
    if st.sidebar.button("로그아웃", use_container_width=True):
        st.session_state['logged_in'] = False
        st.session_state['role'] = ""
        st.rerun()

# 8. 대시보드 화면
def dashboard_page():
    st.title("📊 나의 업무 대시보드")
    df = load_data()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("결재 대기", f"{len(df[df['상태'] == '결재대기'])} 건")
    col2.metric("전체 기안", f"{len(df)} 건")
    col3.metric("승인 완료", f"{len(df[df['상태'] == '승인완료'])} 건")
    
    st.markdown("---")
    st.subheader("최근 결재 진행 현황")
    if len(df) > 0:
        st.dataframe(df.iloc[::-1], use_container_width=True, hide_index=True)
    else:
        st.info("아직 작성된 결재 문서가 없습니다.")

# 9. 기안 작성 화면 (직원 전용)
def new_document_page():
    st.title("📝 신규 기안 작성")
    st.markdown("---")
    
    # 폼 영역 (이전 단계 코드와 동일하게 유지)
    doc_type = st.selectbox("📑 문서 양식 선택", ["선택하세요", "신제품 개발 의뢰서", "품질 관리 절차서 (ISO 13485)", "휴가원"])

    if doc_type == "신제품 개발 의뢰서":
        with st.form("dev_request_form"):
            st.subheader("🔬 신제품 개발 의뢰서")
            product_line = st.selectbox("관련 브랜드/제품군", ["Xenosys - Looks", "기타 신규 브랜드"])
            project_name = st.text_input("프로젝트명", value="LooksCAM LT 개발 건")
            dev_purpose = st.text_area("개발 목적 및 기대효과")
            if st.form_submit_button("결재 상신하기", type="primary", use_container_width=True):
                save_data(doc_type, project_name, st.session_state['current_user'])
                st.success(f"'{project_name}' 기안이 상신되었습니다!")

    elif doc_type == "품질 관리 절차서 (ISO 13485)":
        with st.form("quality_form"):
            st.subheader("⚙️ 품질 관리 절차서 제/개정")
            doc_title = st.text_input("문서명 (예: 내부품질감사 규정 개정)")
            revision_reason = st.text_area("제/개정 사유")
            if st.form_submit_button("결재 상신하기", type="primary", use_container_width=True):
                save_data(doc_type, doc_title, st.session_state['current_user'])
                st.success(f"'{doc_title}' 기안이 상신되었습니다!")

    elif doc_type == "휴가원":
        with st.form("vacation_form"):
            st.subheader("🌴 휴가원 (연차/반차/병가 등)")
            col1, col2 = st.columns(2)
            with col1:
                leave_type = st.selectbox("휴가 종류", ["연차", "오전반차", "오후반차", "병가", "경조휴가", "기타"])
            with col2:
                emergency_contact = st.text_input("비상 연락처", placeholder="010-XXXX-XXXX")
            
            col3, col4 = st.columns(2)
            with col3:
                start_date = st.date_input("시작일")
            with col4:
                end_date = st.date_input("종료일")
                
            reason = st.text_area("휴가 사유", placeholder="개인사정, 병원 진료 등")
            if st.form_submit_button("결재 상신하기", type="primary", use_container_width=True):
                doc_title = f"[{leave_type}] {start_date} ~ {end_date} (사유: {reason})"
                save_data(doc_type, doc_title, st.session_state['current_user'])
                st.success(f"{leave_type} 신청이 완료되었습니다! 푹 쉬고 오세요! 🏖️")

# 10. 결재함 화면 (관리자 전용)
def approval_box_page():
    st.title("✅ 결재함 (승인/반려 처리)")
    st.markdown("---")
    df = load_data()
    pending_df = df[df['상태'] == '결재대기']
    if len(pending_df) == 0:
        st.info("🎉 현재 결재 대기 중인 문서가 없습니다.")
    else:
        doc_options = pending_df['문서번호'] + " | " + pending_df['제목']
        selected_doc_str = st.selectbox("검토할 문서를 선택하세요:", doc_options)
        if selected_doc_str:
            selected_doc_no = selected_doc_str.split(" | ")[0]
            doc_info = pending_df[pending_df['문서번호'] == selected_doc_no].iloc[0]
            st.markdown(f"**기안자:** {doc_info['기안자']} | **제목:** {doc_info['제목']}")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🟢 승인하기", use_container_width=True):
                    update_status(selected_doc_no, "승인완료")
                    st.rerun()
            with col2:
                if st.button("🔴 반려하기", use_container_width=True):
                    update_status(selected_doc_no, "반려됨")
                    st.rerun()

# 11. 결재 문서 열람 (공통)
def document_view_page():
    st.title("📄 결재 문서 열람")
    st.markdown("---")
    df = load_data()
    if len(df) == 0:
        st.info("아직 작성된 문서가 없습니다.")
    else:
        doc_options = df['문서번호'] + " | " + df['제목'] + " (" + df['상태'] + ")"
        selected_doc_str = st.selectbox("열람할 문서를 선택하세요:", doc_options.iloc[::-1])
        if selected_doc_str:
            selected_doc_no = selected_doc_str.split(" | ")[0]
            doc_info = df[df['문서번호'] == selected_doc_no].iloc[0]
            st.markdown("### 📋 결재 기안서")
            st.write(f"- **문서 번호:** {doc_info['문서번호']}")
            st.write(f"- **기안자:** {doc_info['기안자']}")
            st.write(f"- **문서 제목:** {doc_info['제목']}")
            st.write(f"- **기안 일자:** {doc_info['기안일']}")
            st.markdown("---")
            if doc_info['상태'] == "승인완료":
                st.success("✅ 이 문서는 관리자의 승인이 완료되었습니다.")
                st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/f/f8/Stylized_signature_of_John_Hancock.png/320px-Stylized_signature_of_John_Hancock.png", width=150)
            elif doc_info['상태'] == "반려됨":
                st.error("❌ 이 문서는 반려되었습니다.")
            else:
                st.warning("⏳ 현재 결재 대기 중입니다.")

# 12. 앱 실행 로직
if st.session_state['logged_in']:
    sidebar_menu() # 공통 메뉴 호출
    
    # 선택된 페이지 보여주기
    if st.session_state['page'] == 'dashboard':
        dashboard_page()
    elif st.session_state['page'] == 'new_document' and st.session_state['role'] == 'employee':
        new_document_page()
    elif st.session_state['page'] == 'approval_box' and st.session_state['role'] == 'manager':
        approval_box_page()
    elif st.session_state['page'] == 'document_view':
        document_view_page()
    else:
        # 권한이 없는 페이지로 접근 시 대시보드로 강제 이동
        dashboard_page()
else:
    login_page()