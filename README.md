# script-library

영어 드라마 대본으로 영어를 공부하기 위한 정적 웹사이트.
영어 대사를 먼저 이해해보고, 토글이나 카드 클릭으로 한글 해석·뉘앙스·예문을 확인하는 방식.

## 기능

- 드라마 단위로 묶인 대본 목록 페이지 + 대본 보기 페이지 (해시 라우팅)
- 대사별 라인 번호, 화자 표시
- 전체 해석 일괄 토글
- `unseen`(원 방영본엔 없던 확장본 부분)은 회색으로 연하게 표시
- 장면 헤딩 `[Scene: ...]`, 섹션 구분(Commercial Break 등), 행동 지침 `(...)` 구분 표시

## 로컬 실행

브라우저의 `file://` 직접 열기는 JSON `fetch`가 CORS로 막히므로 로컬 서버로 실행한다.

```bash
python3 -m http.server 8000
# http://localhost:8000 접속
```

## 구조

```
.
├── index.html        # 목록 + 대본 뷰어 (해시 라우팅)
├── css/style.css
├── js/app.js         # JSON 로드 → 렌더링
├── data/
│   ├── index.json    # 드라마 → 에피소드 목록
│   └── <drama>/<file>.json
└── tools/
    └── import_transcript.py
```

## 대본 추가

- 같은 드라마: `data/<drama>/`에 에피소드 JSON 추가 → `data/index.json`의 해당 드라마 `episodes`에 항목 추가
- 새 드라마: `data/<drama>/` 폴더 + `data/index.json`의 `dramas`에 항목 추가

데이터 형식은 기존 파일을 참고. `english`/`korean`/`text`는 문자열 또는
`[{ "text": "...", "unseen": true }]` 조각 배열을 받는다.
