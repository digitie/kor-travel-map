import { describe, expect, it } from "vitest";

import {
  kraddrCandidateToAddressRecord,
  kraddrCandidateToCoord,
  kraddrCodesFromCandidate,
  type KraddrGeoCandidate,
} from "./kraddrGeo";

const candidate: KraddrGeoCandidate = {
  address: {
    admin_dong_code: "1111053000",
    full: "서울특별시 종로구 사직로 161",
    legal_dong_code: "1111011900",
    parcel_address: "서울특별시 종로구 세종로 1-68",
    postal_code: "03045",
    road_address: "서울특별시 종로구 사직로 161",
    road_name_code: "111103100010",
  },
  point: { x: 126.9769, y: 37.5759 },
  region: {
    bjd_cd: "1111011900",
    sig_cd: "11110",
    sido: "서울특별시",
    sigungu: "종로구",
    legal_dong: "세종로",
    admin_dong: "사직동",
  },
};

describe("kraddrCandidateToCoord", () => {
  it("x/y 좌표를 lon/lat으로 정규화", () => {
    expect(kraddrCandidateToCoord(candidate)).toEqual({
      lon: 126.9769,
      lat: 37.5759,
    });
  });

  it("좌표가 없으면 null", () => {
    expect(kraddrCandidateToCoord({ point: null })).toBeNull();
  });
});

describe("kraddrCodesFromCandidate", () => {
  it("주소와 region 코드에서 admin feature top-level code를 만든다", () => {
    expect(kraddrCodesFromCandidate(candidate)).toEqual({
      admin_dong_code: "1111053000",
      legal_dong_code: "1111011900",
      road_name_code: "111103100010",
      sido_code: "11",
      sigungu_code: "11110",
    });
  });
});

describe("kraddrCandidateToAddressRecord", () => {
  it("Address DTO 호환 object를 만든다", () => {
    expect(kraddrCandidateToAddressRecord(candidate)).toMatchObject({
      admin: "사직동",
      bjd_code: "1111011900",
      legal: "서울특별시 종로구 세종로 1-68",
      road: "서울특별시 종로구 사직로 161",
      sigungu_code: "11110",
      sido_code: "11",
      sido_name: "서울특별시",
      sigungu_name: "종로구",
    });
  });
});
