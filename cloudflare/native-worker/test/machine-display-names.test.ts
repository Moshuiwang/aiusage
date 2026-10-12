import {describe, expect, it} from "vitest";
import {withWorker} from "./golden/harness";
import {fixedNow} from "./golden/paths";

describe("服务端集中机器名称不改变身份或用量", () => {
  it("同机两个OS用户共用显示名称，summary与mobile-summary一致，不同设备同名不合并", async () => {
    await withWorker({now: fixedNow}, async ({fetchRaw}) => {
      const machines = ["wangzhipengdeMac-Mini.local", "wangzhipengdeMac-Mini.local", "wangzhipengdeMac-Mini", "tz"];
      for (const [index,machine] of machines.entries()) {
        const result=await fetchRaw({method:"POST",path:"/ingest",auth:true,body:{schema_version:1,
          source_id:`name-source-${index}`,host:machine,machine,os_user:`user-${index}`,platform:"darwin",timezone:"Asia/Shanghai",
          observed_at:"2026-06-03T11:00:00+08:00",usage_hourly_facts:[{fact_id:`name-fact-${index}`,agent:"claude",
            window_start:"2026-06-03T10:00:00+08:00",window_end:"2026-06-03T11:00:00+08:00",
            usage:{input_tokens:100,output_tokens:0,total_tokens:100},attribution_confidence:"observed",provenance:"test"}]}});
        expect(result.status).toBe(200);
      }
      const read=async(path:string)=>{
        const response=await fetchRaw({path,auth:true});expect(response.status).toBe(200);
        return JSON.parse(response.body.toString("utf8"));
      };
      const mobile=await read("/api/mobile/summary?period=today&offset=0");
      expect(mobile.period.total_tokens).toBe(400);
      expect(mobile.breakdown.by_machine).toHaveLength(3);
      const mini=mobile.breakdown.by_machine.find((r:{id:string})=>r.id==="wangzhipengdeMac-Mini.local");
      expect(mini).toMatchObject({label:"Mac mini",tokens:200,source_ids:["name-source-0","name-source-1"]});
      expect(new Set(mobile.sources.filter((r:{source_id:string})=>mini.source_ids.includes(r.source_id)).map((r:{os_user:string})=>r.os_user))).toEqual(new Set(["user-0","user-1"]));
      expect(mobile.breakdown.by_machine.filter((r:{label:string})=>r.label==="Mac mini")).toHaveLength(2);
      expect(mobile.breakdown.by_machine.find((r:{id:string})=>r.id==="tz").label).toBe("TZ");
      expect(mobile.sources.find((r:{source_id:string})=>r.source_id==="name-source-0")).toMatchObject({machine:"wangzhipengdeMac-Mini.local",display_name:"Mac mini · user-0"});
      const full=await read("/api/summary?period=today&offset=0");
      expect(full.groups.by_machine.find((r:{name:string})=>r.name==="wangzhipengdeMac-Mini.local")).toMatchObject({display_name:"Mac mini",total_tokens:200});
    });
  },60000);
});
