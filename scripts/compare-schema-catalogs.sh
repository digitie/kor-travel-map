#!/usr/bin/env bash
# 두 DB의 카탈로그를 행 단위로 대조한다. alembic squash 동등성 증명의 오라클이다.
#
# 왜 새로 만들지 않고 추출하는가:
#   비교 SQL은 `run-admin-feature-clone-live-acceptance.sh`의 `schema_sha256()`이
#   이미 갖고 있다(304줄). 손으로 복사하면 두 사본이 조용히 어긋난다 — 이 저장소가
#   2026-08-13에만 세 번 겪은 결함 부류다(0102 anchor 불일치, 0104가 hardening 이전
#   원문에서 재생성, live fixture 감사 누락). 그래서 **런타임에 추출**해 정본을 하나로 둔다.
#
# 왜 해시가 아니라 행을 내는가:
#   해시만 비교하면 "다르다"까지만 알 수 있다. squash 검증은 "무엇이 다른가"가 필요하고,
#   그 차이가 의미 있는 것인지(스키마 변경) 표현 차이인지(dump/restore 왕복 불안정)를
#   사람이 판정해야 한다. 실제로 2026-08-13에 그 판정이 `proacl` 물화 문제를 찾아냈다.
#
# 사용:
#   scripts/compare-schema-catalogs.sh <container> <db-a> <db-b> [--admin-user U]
#   scripts/compare-schema-catalogs.sh --self-test <container> <db> [--admin-user U]
#
# `--self-test`는 **오라클을 먼저 증명한다**. 스크래치 DB를 두 벌 만들고 한쪽에만
# 알려진 변조를 주입해, 비교기가 그것을 실제로 잡는지 확인한다. 검사기가 검사 대상을
# 안 보는데 초록인 상태가 이 저장소의 지배적 실패 양식이므로, 어떤 초록도 이 검증
# 없이는 근거가 아니다.
set -euo pipefail

die() { printf 'compare-schema-catalogs: %s\n' "$1" >&2; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
RUNNER="$SCRIPT_DIR/run-admin-feature-clone-live-acceptance.sh"
[ -f "$RUNNER" ] || die "digest SQL 원본을 찾지 못했다: $RUNNER"

ADMIN_USER=""
SELF_TEST=0
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --self-test) SELF_TEST=1; shift ;;
    --admin-user) ADMIN_USER="${2:?--admin-user needs a value}"; shift 2 ;;
    -*) die "알 수 없는 옵션: $1" ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

extract_digest_sql() {
  # `schema_sha256() { ... query="$(cat <<'SQL' ... SQL ... }` 에서 SQL 본문만.
  python3 - "$RUNNER" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
try:
    body = src[src.index("schema_sha256() {"):]
    start = body.index("<<'SQL'\n") + len("<<'SQL'\n")
    end = body.index("\nSQL\n", start)
except ValueError:
    raise SystemExit("schema_sha256()의 SQL 헤어독 경계를 찾지 못했다")
sql = body[start:end]
if "COPY (" not in sql or "pg_catalog.pg_class" not in sql:
    raise SystemExit("추출한 SQL이 카탈로그 질의로 보이지 않는다")
print(sql)
PY
}

extract_grantee_values() {
  # routine 유효권한 축의 grantee 목록. **정본은 `build-baseline.sh`의
  # `ROUTINE_ACL_GRANTEE_VALUES`**이고 여기서는 추출한다 — 손으로 복제하면 그쪽이
  # 늘어났을 때 여기만 줄어들고, **A/B 비교라 양쪽 다 그 축을 안 보게 되어 초록이
  # 유지된다.** 검사기와 검사 대상이 맹점을 공유하는 그 패턴이다. 이 파일 상단이
  # digest SQL에 대해 선언한 "복사하지 말고 추출한다" 원칙을 목록에도 적용한다.
  python3 - "$SCRIPT_DIR/build-baseline.sh" <<'PY'
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
match = re.search(r'ROUTINE_ACL_GRANTEE_VALUES="(.*?)"', src, re.DOTALL)
if match is None:
    raise SystemExit("build-baseline.sh에서 ROUTINE_ACL_GRANTEE_VALUES를 찾지 못했다")
values = " ".join(match.group(1).split())
if values.count("(") < 2:
    raise SystemExit(f"추출한 grantee 목록이 값 목록으로 보이지 않는다: {values[:80]!r}")
print(values)
PY
}

supplementary_sql() {
  # 추출한 digest SQL이 **보지 않는** 축. 그 SQL의 namespace 필터는 pg_dump의 `-n`
  # 스코프(feature/provider_sync/ops)와 정확히 같아서, **baseline이 재현하지 못하는
  # 것은 오라클도 검사하지 못한다.** 검사기와 검사 대상이 맹점을 공유하는 구조다.
  #
  # 실제로 그 틈으로 결함이 새어 나왔다(2026-08-14): 체인이 `0095`에서 주던
  # `GRANT USAGE ON SCHEMA x_extension TO ktm_feature_runtime`이 baseline에 없어
  # 새 DB의 runtime이 PostGIS를 통째로 잃었는데, 카탈로그는 2486행 전부 일치였다.
  #
  # 그래서 스코프 **밖**을 본다: 모든 스키마의 소유자·ACL, `public`에 남은 객체,
  # event trigger, database 소유자·ACL. 그리고 스코프 안이지만 축이 빠져 있던
  # 제약 **정의**(원본 SQL은 이름·유형·컬럼만 본다).
  #
  # database 이름은 넣지 않는다 — 비교 대상 두 DB는 이름이 다르므로 항상 어긋난다.
  cat <<'SQL'
;
COPY (
  SELECT 'schemaacl' || nsp.nspname || ':' || pg_catalog.pg_get_userbyid(nsp.nspowner) || ':' ||
         COALESCE((SELECT string_agg(entry::text, ',' ORDER BY entry::text)
                     FROM unnest(nsp.nspacl) AS entry), '')
    FROM pg_catalog.pg_namespace AS nsp
   WHERE nsp.nspname NOT LIKE 'pg\_%' AND nsp.nspname <> 'information_schema'
  UNION ALL
  -- extension은 schema 이름만으로 scope를 자르지 않는다. `pg_catalog`은 implicit
  -- search_path이고, public/x_extension 밖의 unknown extension도 member residue를
  -- 숨길 수 있다. header의 owner/version/config/condition까지 full inventory로 비교한다.
  SELECT 'extension' || nsp.nspname || ':' || ext.extname || ':' ||
         pg_catalog.pg_get_userbyid(ext.extowner) || ':' || ext.extrelocatable::text || ':' ||
         ext.extversion || ':' ||
         COALESCE((SELECT string_agg(cfg_nsp.nspname || chr(30) || cfg_rel.relname,
                                      chr(29) ORDER BY cfg.ordinality)
                     FROM unnest(ext.extconfig) WITH ORDINALITY AS cfg(relid, ordinality)
                     JOIN pg_catalog.pg_class AS cfg_rel ON cfg_rel.oid = cfg.relid
                     JOIN pg_catalog.pg_namespace AS cfg_nsp ON cfg_nsp.oid = cfg_rel.relnamespace), '') || ':' ||
         COALESCE(ext.extcondition::text, '')
    FROM pg_catalog.pg_extension AS ext
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = ext.extnamespace
  UNION ALL
  SELECT 'rule' || nsp.nspname || '.' || rel.relname || ':' || rule.rulename || ':' ||
         pg_catalog.pg_get_ruledef(rule.oid, true)
    FROM pg_catalog.pg_rewrite AS rule
    JOIN pg_catalog.pg_class AS rel ON rel.oid = rule.ev_class
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = rel.relnamespace
   WHERE nsp.nspname IN ('feature', 'provider_sync', 'ops')
     AND rule.rulename <> '_RETURN'
  UNION ALL
  SELECT 'inheritance' || child_nsp.nspname || '.' || child.relname || ':' ||
         parent_nsp.nspname || '.' || parent.relname || ':' || inherit.inhseqno::text
    FROM pg_catalog.pg_inherits AS inherit
    JOIN pg_catalog.pg_class AS child ON child.oid = inherit.inhrelid
    JOIN pg_catalog.pg_namespace AS child_nsp ON child_nsp.oid = child.relnamespace
    JOIN pg_catalog.pg_class AS parent ON parent.oid = inherit.inhparent
    JOIN pg_catalog.pg_namespace AS parent_nsp ON parent_nsp.oid = parent.relnamespace
   WHERE child_nsp.nspname IN ('feature', 'provider_sync', 'ops')
      OR parent_nsp.nspname IN ('feature', 'provider_sync', 'ops')
  UNION ALL
  SELECT 'partitioned' || nsp.nspname || '.' || rel.relname || ':' || part.partstrat::text || ':' ||
         pg_catalog.pg_get_partkeydef(part.partrelid) || ':' ||
         COALESCE(default_nsp.nspname || '.' || default_rel.relname, '')
    FROM pg_catalog.pg_partitioned_table AS part
    JOIN pg_catalog.pg_class AS rel ON rel.oid = part.partrelid
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = rel.relnamespace
    LEFT JOIN pg_catalog.pg_class AS default_rel ON default_rel.oid = part.partdefid
    LEFT JOIN pg_catalog.pg_namespace AS default_nsp ON default_nsp.oid = default_rel.relnamespace
   WHERE nsp.nspname IN ('feature', 'provider_sync', 'ops')
  UNION ALL
  SELECT 'foreigntable' || nsp.nspname || '.' || rel.relname || ':' || srv.srvname || ':' ||
         fdw.fdwname || ':' || md5(COALESCE(array_to_string(ft.ftoptions, chr(30)), ''))
    FROM pg_catalog.pg_foreign_table AS ft
    JOIN pg_catalog.pg_class AS rel ON rel.oid = ft.ftrelid
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = rel.relnamespace
    JOIN pg_catalog.pg_foreign_server AS srv ON srv.oid = ft.ftserver
    JOIN pg_catalog.pg_foreign_data_wrapper AS fdw ON fdw.oid = srv.srvfdw
   WHERE nsp.nspname IN ('feature', 'provider_sync', 'ops')
  UNION ALL
  SELECT 'foreignserver' || srv.srvname || ':' || pg_catalog.pg_get_userbyid(srv.srvowner) || ':' ||
         fdw.fdwname || ':' || COALESCE(srv.srvtype, '') || ':' || COALESCE(srv.srvversion, '') || ':' ||
         md5(COALESCE(array_to_string(fdw.fdwoptions, chr(30)), '')) || ':' ||
         md5(COALESCE(array_to_string(srv.srvoptions, chr(30)), ''))
    FROM pg_catalog.pg_foreign_server AS srv
    JOIN pg_catalog.pg_foreign_data_wrapper AS fdw ON fdw.oid = srv.srvfdw
   WHERE EXISTS (
       SELECT 1
       FROM pg_catalog.pg_foreign_table AS ft
       JOIN pg_catalog.pg_class AS rel ON rel.oid = ft.ftrelid
       JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = rel.relnamespace
       WHERE ft.ftserver = srv.oid
         AND nsp.nspname IN ('feature', 'provider_sync', 'ops')
   )
  UNION ALL
  SELECT 'usermapping' || srv.srvname || ':' ||
         CASE WHEN mapping.umuser = 0 THEN 'public' ELSE mapping.umuser::regrole::text END || ':' ||
         md5(COALESCE(array_to_string(mapping.umoptions, chr(30)), ''))
    FROM pg_catalog.pg_user_mapping AS mapping
    JOIN pg_catalog.pg_foreign_server AS srv ON srv.oid = mapping.umserver
   WHERE EXISTS (
       SELECT 1
       FROM pg_catalog.pg_foreign_table AS ft
       JOIN pg_catalog.pg_class AS rel ON rel.oid = ft.ftrelid
       JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = rel.relnamespace
       WHERE ft.ftserver = srv.oid
         AND nsp.nspname IN ('feature', 'provider_sync', 'ops')
   )
  UNION ALL
  SELECT 'publication' || publication.pubname || ':' ||
         pg_catalog.pg_get_userbyid(publication.pubowner) || ':' || publication.puballtables::text || ':' ||
         publication.pubinsert::text || ':' || publication.pubupdate::text || ':' ||
         publication.pubdelete::text || ':' || publication.pubtruncate::text || ':' || publication.pubviaroot::text
    FROM pg_catalog.pg_publication AS publication
  UNION ALL
  SELECT 'subscription' || subscription.subname || ':' ||
         pg_catalog.pg_get_userbyid(subscription.subowner) || ':' || subscription.subenabled::text || ':' ||
         subscription.subbinary::text || ':' || subscription.substream::text || ':' ||
         subscription.subtwophasestate::text || ':' || subscription.subdisableonerr::text || ':' ||
         subscription.subpasswordrequired::text || ':' || subscription.subrunasowner::text || ':' ||
         md5(COALESCE(subscription.subconninfo, '')) || ':' || COALESCE(subscription.subslotname, '') || ':' ||
         subscription.subsynccommit || ':' || COALESCE(array_to_string(subscription.subpublications, chr(30)), '') || ':' ||
         COALESCE(subscription.suborigin, '')
    FROM pg_catalog.pg_subscription AS subscription
  UNION ALL
  SELECT 'publicrel' || cls.relkind::text || ':' || cls.relname || ':' ||
         pg_catalog.pg_get_userbyid(cls.relowner)
    FROM pg_catalog.pg_class AS cls
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = cls.relnamespace
   WHERE nsp.nspname = 'public'
  UNION ALL
  SELECT 'publicproc' || pro.proname || '(' ||
         pg_catalog.pg_get_function_identity_arguments(pro.oid) || ')'
    FROM pg_catalog.pg_proc AS pro
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = pro.pronamespace
   WHERE nsp.nspname = 'public'
  UNION ALL
  SELECT 'evttrigger' || evt.evtname || ':' || evt.evtevent || ':' || evt.evtenabled::text || ':' ||
         pg_catalog.pg_get_userbyid(evt.evtowner)
    FROM pg_catalog.pg_event_trigger AS evt
  UNION ALL
  -- 소유자는 넣지 않는다. DB 이름과 마찬가지로 **bootstrap/provisioning이 정하는 값**이라
  -- 스키마와 무관한 빨강을 만든다(복원 DB를 `postgres` 소유로 만들어 대조하는 경우).
  -- locale/encoding은 넣는다 — 이 저장소는 collation이 load-bearing이다
  -- (`tests/integration/test_alias_map_collation_glibc.py`).
  SELECT 'dbprops' || db.encoding::text || ':' || db.datcollate || ':' || db.datctype || ':' ||
         db.datlocprovider::text || ':' ||
         COALESCE((SELECT string_agg(entry::text, ',' ORDER BY entry::text)
                     FROM unnest(db.datacl) AS entry), '')
    FROM pg_catalog.pg_database AS db
   WHERE db.datname = current_database()
  UNION ALL
  -- routine 유효권한. 추출한 원본 SQL의 routine 축은 `acldefault` 문자열 차감이라
  -- **PUBLIC EXECUTE 재부여를 못 본다**(함수 기본 ACL에 PUBLIC이 들어 있어 같이 지워진다).
  -- `has_function_privilege()`로 직접 물어 그 구멍을 메운다.
  SELECT 'routineacl' || grantee.name || '|' || n.nspname || '.' || p.proname
         || '(' || pg_catalog.pg_get_function_identity_arguments(p.oid) || ')'
         || '|execute=' || pg_catalog.has_function_privilege(grantee.name, p.oid, 'EXECUTE')::text
         || '|grantopt=' || pg_catalog.has_function_privilege(grantee.name, p.oid,
                                                              'EXECUTE WITH GRANT OPTION')::text
    FROM pg_catalog.pg_proc AS p
    JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
    CROSS JOIN (VALUES @GRANTEES@) AS grantee(name)
   WHERE n.nspname IN ('feature', 'provider_sync', 'ops')
  UNION ALL
  SELECT 'constraintdef' || nsp.nspname || '.' || rel.relname || '.' || con.conname || ':' ||
         pg_catalog.pg_get_constraintdef(con.oid)
    FROM pg_catalog.pg_constraint AS con
    JOIN pg_catalog.pg_class AS rel ON rel.oid = con.conrelid
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = rel.relnamespace
   WHERE nsp.nspname IN ('feature', 'provider_sync', 'ops')
  UNION ALL
  SELECT 'attstats' || nsp.nspname || '.' || cls.relname || '.' ||
         CASE WHEN cls.relkind = 'i' THEN 'col' || att.attnum::text ELSE att.attname END ||
         ':' || cls.relkind::text ||
         ':' || COALESCE(att.attstattarget::text, 'default') ||
         ':' || COALESCE((SELECT string_agg(opt, ',' ORDER BY opt)
                            FROM unnest(att.attoptions) AS opt), '')
    FROM pg_catalog.pg_attribute AS att
    JOIN pg_catalog.pg_class AS cls ON cls.oid = att.attrelid
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = cls.relnamespace
   WHERE nsp.nspname IN ('feature', 'provider_sync', 'ops')
     AND cls.relkind IN ('r', 'p', 'v', 'm', 'f', 'i')
     AND att.attnum > 0
     AND NOT att.attisdropped
  UNION ALL
  -- 컬럼 저장 속성(attstorage / attcompression). 추출한 digest SQL의 'column' 축은
  -- 이름·format_type·attnotnull·attidentity·attgenerated·attacl·기본값까지만 본다 —
  -- **저장 전략은 두 오라클 어디에도 없다**(`rg 'attstorage|attcompression|typstorage'`
  -- 가 compare-schema-catalogs.sh / run-admin-feature-clone-live-acceptance.sh 양쪽에서
  -- 0건). `ALTER TABLE ... SET STORAGE|SET COMPRESSION`은 pg_attribute의 이 두 칸만
  -- 쓰므로, 체인에는 있고 baseline에는 없는 저장 속성 마이그레이션이 통째로 새어 나간다.
  --
  -- relkind는 PG16의 ATExecSetStorage/ATExecSetCompression이 허용하는 것만 넣는다
  -- (ATT_TABLE = 'r'/'p', ATT_MATVIEW = 'm', ATT_FOREIGN_TABLE = 'f'). 나머지는 검출력이
  -- 0이거나 비결정적이다:
  --   'v' 뷰   — SET STORAGE 자체가 거부되고 attstorage는 타입 기본값을 절대 벗어나지
  --              못한다. 타입이 바뀌면 column 축(format_type)이 이미 잡는다.
  --   'i'/'I' — 인덱스 컬럼 attstorage는 DDL로 바꿀 수 없다(SET STATISTICS만 가능).
  --              SET STORAGE는 단순 인덱스 컬럼에 전파되지만 그건 **파생값**이라
  --              같은 변경을 두 번 세게 만들 뿐이다. 게다가 식 인덱스 컬럼 이름은
  --              pg_expression_N 파생이다.
  --   'S' 시퀀스 — last_value/log_cnt/is_called 고정 3칸, 항상 plain. 정보량 0.
  --   't' TOAST — nspname 필터(pg_toast)로 이미 빠지지만, relname이 OID 파생
  --              (pg_toast_16384)이라 **두 DB에서 항상 어긋난다**. 결정론 위반.
  --   'c' 복합타입 — SET STORAGE DDL이 없다. type 축이 이미 본다.
  -- 'p'/'m'/'f'는 이 스키마에 아직 없지만(2026-08-14 실측 전부 'r') 파티션 도입 시
  -- 조용히 맹점이 되지 않도록 미리 넣는다.
  --
  -- attnum이 아니라 **컬럼 이름**으로 키를 잡는다 — DROP COLUMN이 남기는 attnum gap
  -- (feature.features는 7·20·22·25·27~34가 비어 있다)을 dump/restore가 메꾸므로
  -- ordinal을 넣으면 표현 차이만으로 빨강이 된다.
  --
  -- 라벨로 펴서 낸다: 압축 pglz의 카탈로그 값이 'p'라 저장속성 'p'(plain)와 인접
  -- 필드에서 눈으로 헷갈린다. 미지의 신규 압축 메서드는 unknown(<char>)로 드러난다.
  SELECT 'attstorage' || nsp.nspname || '.' || cls.relname || '.' || att.attname || ':' ||
         CASE att.attstorage::text
           WHEN 'p' THEN 'plain'
           WHEN 'e' THEN 'external'
           WHEN 'm' THEN 'main'
           WHEN 'x' THEN 'extended'
           ELSE 'unknown(' || COALESCE(att.attstorage::text, '') || ')'
         END || ':' ||
         CASE att.attcompression::text
           WHEN 'p' THEN 'pglz'
           WHEN 'l' THEN 'lz4'
           WHEN '' THEN 'default'
           ELSE 'unknown(' || COALESCE(att.attcompression::text, '') || ')'
         END
    FROM pg_catalog.pg_attribute AS att
    JOIN pg_catalog.pg_class AS cls ON cls.oid = att.attrelid
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = cls.relnamespace
   WHERE nsp.nspname IN ('feature', 'provider_sync', 'ops')
     AND cls.relkind IN ('r', 'p', 'm', 'f')
     AND att.attnum > 0
     AND NOT att.attisdropped
  UNION ALL
  SELECT 'comment' || axis.entry
    FROM (
      WITH scoped AS (
        SELECT 'relation'::text AS kind,
               nsp.nspname::text AS schema_name,
               nsp.nspname || '.' || cls.relname || ':' || cls.relkind::text AS ident,
               dsc.description AS body
          FROM pg_catalog.pg_description AS dsc
          JOIN pg_catalog.pg_class AS cls ON cls.oid = dsc.objoid
          JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = cls.relnamespace
         WHERE dsc.classoid = 'pg_catalog.pg_class'::regclass
           AND dsc.objsubid = 0
           AND cls.relkind <> 't'::"char"
           AND nsp.nspname IN ('feature', 'provider_sync', 'ops')
        UNION ALL
        SELECT 'column'::text,
               nsp.nspname::text,
               nsp.nspname || '.' || cls.relname || '.' || att.attname,
               dsc.description
          FROM pg_catalog.pg_description AS dsc
          JOIN pg_catalog.pg_class AS cls ON cls.oid = dsc.objoid
          JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = cls.relnamespace
          JOIN pg_catalog.pg_attribute AS att
            ON att.attrelid = dsc.objoid AND att.attnum = dsc.objsubid
         WHERE dsc.classoid = 'pg_catalog.pg_class'::regclass
           AND dsc.objsubid > 0
           AND NOT att.attisdropped
           AND nsp.nspname IN ('feature', 'provider_sync', 'ops')
        UNION ALL
        SELECT 'routine'::text,
               nsp.nspname::text,
               nsp.nspname || '.' || pro.proname || '(' ||
                 pg_catalog.pg_get_function_identity_arguments(pro.oid) || ')',
               dsc.description
          FROM pg_catalog.pg_description AS dsc
          JOIN pg_catalog.pg_proc AS pro ON pro.oid = dsc.objoid
          JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = pro.pronamespace
         WHERE dsc.classoid = 'pg_catalog.pg_proc'::regclass
           AND nsp.nspname IN ('feature', 'provider_sync', 'ops')
        UNION ALL
        SELECT 'constraint'::text,
               nsp.nspname::text,
               nsp.nspname || '.' || COALESCE(rel.relname, typ.typname, '?') || '.' ||
                 con.conname || ':' || con.contype::text,
               dsc.description
          FROM pg_catalog.pg_description AS dsc
          JOIN pg_catalog.pg_constraint AS con ON con.oid = dsc.objoid
          JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = con.connamespace
          LEFT JOIN pg_catalog.pg_class AS rel ON rel.oid = con.conrelid
          LEFT JOIN pg_catalog.pg_type AS typ ON typ.oid = con.contypid
         WHERE dsc.classoid = 'pg_catalog.pg_constraint'::regclass
           AND nsp.nspname IN ('feature', 'provider_sync', 'ops')
      )
      SELECT scoped.kind || ':' || scoped.ident || ':' || COALESCE(scoped.body, '')
        FROM scoped
      UNION ALL
      SELECT 'census:' || s.schema_name || ':' || k.kind || ':' ||
             (SELECT count(*) FROM scoped
               WHERE scoped.schema_name = s.schema_name AND scoped.kind = k.kind)::text
        FROM (VALUES ('feature'), ('ops'), ('provider_sync')) AS s(schema_name)
        CROSS JOIN (VALUES ('relation'), ('column'), ('routine'), ('constraint')) AS k(kind)
    ) AS axis(entry)
  UNION ALL
  SELECT 'extstats' || stx_nsp.nspname || '.' || stx.stxname || ':' ||
         rel_nsp.nspname || '.' || rel.relname || ':' ||
         pg_catalog.pg_get_userbyid(stx.stxowner) || ':' ||
         COALESCE((SELECT string_agg(kind::text, ',' ORDER BY kind::text)
                     FROM unnest(stx.stxkind) AS kind), '') || ':' ||
         COALESCE((SELECT string_agg(att.attname, ',' ORDER BY key.ord)
                     FROM unnest(stx.stxkeys::smallint[]) WITH ORDINALITY AS key(attnum, ord)
                     JOIN pg_catalog.pg_attribute AS att
                       ON att.attrelid = stx.stxrelid AND att.attnum = key.attnum), '') || ':' ||
         COALESCE(stx.stxstattarget::text, '') || ':' ||
         COALESCE(pg_catalog.pg_get_statisticsobjdef(stx.oid), '')
    FROM pg_catalog.pg_statistic_ext AS stx
    JOIN pg_catalog.pg_namespace AS stx_nsp ON stx_nsp.oid = stx.stxnamespace
    JOIN pg_catalog.pg_class AS rel ON rel.oid = stx.stxrelid
    JOIN pg_catalog.pg_namespace AS rel_nsp ON rel_nsp.oid = rel.relnamespace
   WHERE stx_nsp.nspname IN ('feature', 'provider_sync', 'ops')
      OR rel_nsp.nspname IN ('feature', 'provider_sync', 'ops')
  UNION ALL
  SELECT 'reloptions' || nsp.nspname || '.' || cls.relname || ':' || cls.relkind::text || ':' ||
         COALESCE((SELECT string_agg(opt, ',' ORDER BY opt)
                     FROM unnest(cls.reloptions) AS opt), '') || ':toast=' ||
         COALESCE((SELECT string_agg(toast_opt, ',' ORDER BY toast_opt)
                     FROM unnest(toast_rel.reloptions) AS toast_opt), '')
    FROM pg_catalog.pg_class AS cls
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = cls.relnamespace
    LEFT JOIN pg_catalog.pg_class AS toast_rel ON toast_rel.oid = cls.reltoastrelid
   WHERE nsp.nspname IN ('feature', 'provider_sync', 'ops')
     AND cls.relkind IN ('r', 'p', 'v', 'm')
  UNION ALL
  -- relpersistence(p/u/t). digest SQL의 `relation` 축은 relkind·소유자·ACL·RLS·relpartbound만
  -- 보고, 보강 축 어디에도 이 컬럼이 없다 (`rg relpersistence`로 두 SQL 모두 0건 확인).
  -- 그래서 `ALTER TABLE ... SET UNLOGGED`는 카탈로그 전 행 일치를 유지한 채 통과한다.
  -- UNLOGGED는 crash 후 테이블이 TRUNCATE된다는 뜻이므로 성능 옵션이 아니라 내구성
  -- 계약이고, squash baseline이 조용히 바꿀 수 있으면 안 된다.
  --
  -- relkind 스코프는 digest `relation` 축과 **똑같이** 맞춘다('r','p','v','m','S').
  -- 같은 relation 우주를 쓰면 두 축의 행이 1:1로 정렬돼 사람이 diff를 읽기 쉽다.
  -- 'v'는 항상 'p'라 신호가 없지만 1행이므로 정렬을 위해 남긴다.
  --
  -- TOAST('t')는 nspname 필터가 이미 배제한다 — TOAST relation은 `pg_toast` 스키마
  -- 소속이라 3개 스키마 필터에 걸리지 않는다. 넣었다면 relname이 `pg_toast_<oid>`
  -- (실측: `pg_toast_100019`)라 두 DB의 oid가 달라 **항상 빨강**이 됐을 것이다.
  --
  -- 인덱스('i','I')도 뺀다. index persistence는 독립 설정이 불가능하고
  -- (`ALTER INDEX ... SET UNLOGGED` 문법 자체가 없다) 부모 테이블을 그대로 따라가므로,
  -- 316행이 92행 테이블 축의 함수에 불과하다 — 검출력 0, 축 크기만 4배(107→423).
  SELECT 'relpersist' || nsp.nspname || '.' || cls.relname || ':' ||
         COALESCE(cls.relkind::text, '') || ':' ||
         COALESCE(cls.relpersistence::text, '')
    FROM pg_catalog.pg_class AS cls
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = cls.relnamespace
   WHERE nsp.nspname IN ('feature', 'provider_sync', 'ops')
     AND cls.relkind IN ('r', 'p', 'v', 'm', 'S')
  UNION ALL
  SELECT 'replicaidentity' || nsp.nspname || '.' || cls.relname || ':' ||
         cls.relreplident::text || ':' ||
         COALESCE((SELECT string_agg(idx.relname, ',' ORDER BY idx.relname)
                     FROM pg_catalog.pg_index AS ind
                     JOIN pg_catalog.pg_class AS idx ON idx.oid = ind.indexrelid
                    WHERE ind.indrelid = cls.oid AND ind.indisreplident), '')
    FROM pg_catalog.pg_class AS cls
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = cls.relnamespace
   WHERE nsp.nspname IN ('feature', 'provider_sync', 'ops')
     AND cls.relkind IN ('r', 'p', 'm')
  UNION ALL
  SELECT 'seqowned' || seqnsp.nspname || '.' || seqcls.relname || '|ownedby=' ||
         COALESCE(
           (SELECT string_agg(
                     ownnsp.nspname || '.' || owncls.relname || '.' ||
                     COALESCE(ownatt.attname, '<whole-relation>') || ':' || dep.deptype::text,
                     ',' ORDER BY ownnsp.nspname, owncls.relname,
                                  COALESCE(ownatt.attname, '<whole-relation>'), dep.deptype::text)
              FROM pg_catalog.pg_depend AS dep
              JOIN pg_catalog.pg_class AS owncls ON owncls.oid = dep.refobjid
              JOIN pg_catalog.pg_namespace AS ownnsp ON ownnsp.oid = owncls.relnamespace
              LEFT JOIN pg_catalog.pg_attribute AS ownatt
                ON ownatt.attrelid = dep.refobjid
               AND ownatt.attnum = dep.refobjsubid
             WHERE dep.classid = 'pg_catalog.pg_class'::regclass
               AND dep.objid = seq.seqrelid
               AND dep.refclassid = 'pg_catalog.pg_class'::regclass
               AND dep.deptype IN ('a', 'i')),
           '<none>') ||
         '|as=' || COALESCE(pg_catalog.format_type(seq.seqtypid, NULL), '') ||
         '|inc=' || seq.seqincrement::text ||
         '|min=' || seq.seqmin::text ||
         '|max=' || seq.seqmax::text ||
         '|cache=' || seq.seqcache::text ||
         '|cycle=' || seq.seqcycle::text
    FROM pg_catalog.pg_sequence AS seq
    JOIN pg_catalog.pg_class AS seqcls ON seqcls.oid = seq.seqrelid
    JOIN pg_catalog.pg_namespace AS seqnsp ON seqnsp.oid = seqcls.relnamespace
   WHERE seqnsp.nspname IN ('feature', 'provider_sync', 'ops')
  ORDER BY 1
) TO STDOUT
SQL
}

psql_file() { # container db file
  docker exec -i "$1" psql -U "${ADMIN_USER:-postgres}" -d "$2" -tA -f "$3" 2>&1
}

catalog_of() { # container db out
  docker cp "$QUERY_FILE" "$1":/tmp/ktm-catalog-query.sql >/dev/null
  docker exec "$1" psql -U "${ADMIN_USER:-postgres}" -d "$2" -tA -f /tmp/ktm-catalog-query.sql > "$3" 2>&1
  docker exec "$1" rm -f /tmp/ktm-catalog-query.sql >/dev/null 2>&1 || true
  if grep -qE '^(psql:|ERROR:)' "$3"; then
    printf '카탈로그 질의 실패 (%s/%s):\n' "$1" "$2" >&2
    head -5 "$3" >&2
    return 1
  fi
}

QUERY_FILE="$(mktemp)"
trap 'rm -f "$QUERY_FILE" "${TMP_A:-}" "${TMP_B:-}"' EXIT
extract_digest_sql > "$QUERY_FILE"
printf '추출한 digest SQL: %s줄\n' "$(wc -l < "$QUERY_FILE")"
GRANTEE_VALUES="$(extract_grantee_values)"
supplementary_sql | sed "s/@GRANTEES@/${GRANTEE_VALUES//\//\\/}/" >> "$QUERY_FILE"
grep -q '@GRANTEES@' "$QUERY_FILE" && die 'grantee 목록 치환이 남았다 — 추출/치환을 확인하라'
printf '보강 축: 스키마 ACL(전 스키마) · public 잔여 객체 · event trigger · DB locale/ACL ·\n'
printf '        routine 유효권한 · 제약 정의 · COMMENT · reloptions · relpersistence ·\n'
printf '        attstorage/compression · replica identity · 컬럼 통계 설정 · 확장 통계 · sequence OWNED BY\n'

if [ "$SELF_TEST" = "1" ]; then
  CONTAINER="${ARGS[0]:?container required}"
  BASE_DB="${ARGS[1]:?db required}"
  A="ktm_oracle_control_$$"
  B="ktm_oracle_mutant_$$"
  admin() { docker exec "$CONTAINER" psql -U "${ADMIN_USER:-postgres}" -d postgres -c "$1" >/dev/null 2>&1; }

  printf '\n=== 오라클 자체 검증 ===\n'
  printf '기준 DB %s 를 두 벌 복제한다.\n' "$BASE_DB"
  for db in "$A" "$B"; do
    admin "DROP DATABASE IF EXISTS $db WITH (FORCE)"
    admin "CREATE DATABASE $db TEMPLATE $BASE_DB"
  done

  TMP_A="$(mktemp)"; TMP_B="$(mktemp)"
  catalog_of "$CONTAINER" "$A" "$TMP_A"
  catalog_of "$CONTAINER" "$B" "$TMP_B"
  if ! diff -q "$TMP_A" "$TMP_B" >/dev/null; then
    printf 'FAIL 변조 전인데 두 사본이 다르다 — 비교기가 결정론적이지 않다\n' >&2
    diff "$TMP_A" "$TMP_B" | head -5 >&2
    exit 1
  fi
  printf 'PASS 변조 전 두 사본 동일 (%s행)\n' "$(wc -l < "$TMP_A")"

  # 알려진 변조 7종. 각각이 카탈로그의 **다른 축**을 건드린다 — 하나라도 안 잡히면
  # 그 축은 squash 검증에서 무방비다.
  MUTATIONS=(
    "컬럼 추가|ALTER TABLE feature.features ADD COLUMN ktm_oracle_probe text"
    "NOT NULL 제거|ALTER TABLE provider_sync.source_records ALTER COLUMN raw_payload_hash DROP NOT NULL"
    "인덱스 삭제|DROP INDEX IF EXISTS feature.idx_features_admin_updated_keyset"
    "CHECK 추가|ALTER TABLE feature.features ADD CONSTRAINT ktm_oracle_ck CHECK (row_revision >= 0)"
    "기본값 변경|ALTER TABLE feature.features ALTER COLUMN created_at SET DEFAULT '2000-01-01T00:00:00Z'::timestamptz"
    "소유권 이전|ALTER TABLE ops.feature_overrides OWNER TO ${ADMIN_USER:-postgres}"
    "함수 본문 변경|CREATE OR REPLACE FUNCTION feature.derive_subtype_public_ready() RETURNS trigger LANGUAGE plpgsql AS \$\$BEGIN RETURN NEW; END;\$\$"
    # 보강 축 5종. 축을 넓혀 놓고 자체검증을 안 늘리면 그 축은 여전히 아무것도
    # 증명하지 않은 상태다 — 이번 결함이 새어 나온 통로가 정확히 그것이었다.
    "스키마 ACL 회수(스코프 밖)|REVOKE USAGE ON SCHEMA x_extension FROM ktm_feature_runtime"
    "public에 relation 생성|CREATE TABLE public.ktm_oracle_probe (id integer)"
    "public에 routine 생성|CREATE FUNCTION public.ktm_oracle_probe_fn() RETURNS integer LANGUAGE sql AS \$\$SELECT 1\$\$"
    # 함수는 `x_extension`에 만든다 — 다른 축(3개 스키마 routine · public routine)에
    # 걸리지 않아야 event trigger 축이 **혼자** 검출한 것이 된다.
    "event trigger 생성|CREATE FUNCTION x_extension.ktm_oracle_evt_fn() RETURNS event_trigger LANGUAGE plpgsql AS \$\$BEGIN END;\$\$; CREATE EVENT TRIGGER ktm_oracle_probe_evt ON ddl_command_start EXECUTE FUNCTION x_extension.ktm_oracle_evt_fn()"
    "DB ACL 변경|GRANT CONNECT ON DATABASE $B TO ktm_feature_runtime"
    # routine PUBLIC EXECUTE 재부여. digest는 이제 이것을 잡지만 **오라클은 못 잡았다**
    # (추출한 SQL의 routine 축이 `acldefault` 문자열 차감이라 PUBLIC 항목까지 지운다).
    # 보강 축에 유효권한 행을 넣었으므로 여기서 그것이 실제로 무는지 확인한다.
    "routine PUBLIC EXECUTE 재부여|GRANT EXECUTE ON FUNCTION feature.validate_feature_base_field_value() TO PUBLIC"
    # 잔여 맹점 축 8종(2026-08-14 추가). 각각 그 축이 **혼자** 검출하도록 대상을 골랐다.
    "컬럼 통계 타깃/옵션 변경|ALTER TABLE feature.features ALTER COLUMN row_revision SET STATISTICS 250; ALTER TABLE provider_sync.source_records ALTER COLUMN raw_payload_hash SET (n_distinct = -0.4)"
    "컬럼 저장 속성 변경 (SET STORAGE MAIN + SET COMPRESSION pglz)|ALTER TABLE feature.features ALTER COLUMN name SET STORAGE MAIN, ALTER COLUMN lifecycle_state SET COMPRESSION pglz"
    "컬럼 코멘트 추가|COMMENT ON COLUMN feature.features.row_revision IS 'ktm oracle probe comment'"
    "확장 통계 객체 생성 (CREATE STATISTICS, ndistinct+dependencies 2컬럼)|CREATE STATISTICS feature.ktm_oracle_probe_stat (ndistinct, dependencies) ON kind, category FROM feature.features"
    "storage 파라미터 드리프트 — ops.managed_files fillfactor 90→70 + toast.autovacuum_enabled 추가|ALTER TABLE ops.managed_files SET (fillfactor = 70, toast.autovacuum_enabled = false)"
    "UNLOGGED 전환|ALTER TABLE ops.system_log SET UNLOGGED"
    "replica identity FULL 전환|ALTER TABLE feature.features REPLICA IDENTITY FULL"
    "OWNED BY 링크 절단 (serial sequence를 고아로 만든다)|ALTER SEQUENCE ops.import_jobs_queue_sequence_seq OWNED BY NONE"
    "replica identity USING INDEX|ALTER TABLE feature.features REPLICA IDENTITY USING INDEX uq_features_feature_uuid"
  )
  caught=0; missed=0
  for entry in "${MUTATIONS[@]}"; do
    label="${entry%%|*}"; sql="${entry#*|}"
    admin "DROP DATABASE IF EXISTS $B WITH (FORCE)"
    admin "CREATE DATABASE $B TEMPLATE $BASE_DB"
    if ! docker exec "$CONTAINER" psql -U "${ADMIN_USER:-postgres}" -d "$B" -c "$sql" >/dev/null 2>&1; then
      printf 'SKIP %s (변조 SQL이 이 스키마에 적용되지 않는다)\n' "$label"
      continue
    fi
    catalog_of "$CONTAINER" "$B" "$TMP_B"
    if diff -q "$TMP_A" "$TMP_B" >/dev/null; then
      printf 'FAIL %s — 비교기가 잡지 못했다\n' "$label"
      missed=$((missed + 1))
    else
      printf 'PASS %s (%s행 차이)\n' "$label" "$(diff "$TMP_A" "$TMP_B" | grep -c '^[<>]')"
      caught=$((caught + 1))
    fi
  done

  admin "DROP DATABASE IF EXISTS $A WITH (FORCE)"
  admin "DROP DATABASE IF EXISTS $B WITH (FORCE)"
  printf '\n잡음 %s / 놓침 %s\n' "$caught" "$missed"
  [ "$missed" = "0" ] ||
    die "오라클이 카탈로그 축 $missed개를 보지 못한다 — 이 비교기로는 squash를 증명할 수 없다"
  printf '오라클 검증 통과 — 이 비교기의 초록은 근거로 쓸 수 있다.\n'
  exit 0
fi

CONTAINER="${ARGS[0]:?container required}"
DB_A="${ARGS[1]:?db-a required}"
DB_B="${ARGS[2]:?db-b required}"
TMP_A="$(mktemp)"; TMP_B="$(mktemp)"
catalog_of "$CONTAINER" "$DB_A" "$TMP_A"
catalog_of "$CONTAINER" "$DB_B" "$TMP_B"
printf '%s: %s행 / %s: %s행\n' "$DB_A" "$(wc -l < "$TMP_A")" "$DB_B" "$(wc -l < "$TMP_B")"

# 제약 **정의**(`constraintdef`) 축은 따로 낸다. dump된 식을 다시 파싱하면
# PostgreSQL이 같은 의미를 다르게 deparse한다(AND 평탄화, cast 위치). 그 표현 차이를
# 자동으로 지우려 들면 `A AND (B OR C)` 와 `(A AND B) OR C` 처럼 **의미가 다른**
# 재괄호화까지 함께 지워진다 — 괄호를 떼어 비교하면 두 식의 토큰 열이 같아진다.
# 그래서 지우지 않고 **분리해서 보여 준다.** 사람이 판정하는 것이 이 축의 설계다.
CORE_A="$(mktemp)"; CORE_B="$(mktemp)"
CON_A="$(mktemp)"; CON_B="$(mktemp)"
trap 'rm -f "$QUERY_FILE" "${TMP_A:-}" "${TMP_B:-}" "$CORE_A" "$CORE_B" "$CON_A" "$CON_B"' EXIT
grep -v '^constraintdef' "$TMP_A" > "$CORE_A"; grep '^constraintdef' "$TMP_A" > "$CON_A" || true
grep -v '^constraintdef' "$TMP_B" > "$CORE_B"; grep '^constraintdef' "$TMP_B" > "$CON_B" || true

status=0
if diff -q "$CORE_A" "$CORE_B" >/dev/null; then
  printf '카탈로그 동일 — sha256 %s (%s행)\n' \
    "$(sha256sum < "$CORE_A" | awk '{print $1}')" "$(wc -l < "$CORE_A")"
else
  printf '카탈로그 차이 %s행:\n' "$(diff "$CORE_A" "$CORE_B" | grep -c '^[<>]')"
  diff "$CORE_A" "$CORE_B" | head -40 | cut -c1-200
  status=1
fi

if diff -q "$CON_A" "$CON_B" >/dev/null; then
  printf '제약 정의 동일 (%s행)\n' "$(wc -l < "$CON_A")"
else
  printf '\n제약 정의 차이 %s행 — **판정 필요** (deparse 표현 차이인지 의미 차이인지):\n' \
    "$(diff "$CON_A" "$CON_B" | grep -c '^[<>]')"
  diff "$CON_A" "$CON_B" | cut -c1-220
  printf '판정 결과는 PR/문서에 남겨라. 자동으로 지우지 않는다.\n'
  status=1
fi
exit "$status"
