import { expect,it } from "vitest";
import { mockApi,setDemoLatency,demoDesignFingerprint } from "../../src/demo/mockApi";
import { runDesignBasis } from "../../src/results/model";
it("preserves the demo fixture hash and current-run identity for report metadata, while tilt still changes it",async()=>{
 setDemoLatency(0);const view=await mockApi.project("demo-project"),bundle=view.bundle;
 const expected=demoDesignFingerprint(bundle);
 expect(expected).toBe("demo-fnv1a:9365d6de");
 for(const [key,value] of [["address",{text:"Synthetic"}],["installation",{installationType:"hybrid",bessEnergyKwh:10}]]){
  const changed=structuredClone(view);Object.assign(changed.bundle.project.site,{[String(key)]:value});
  const fingerprint=demoDesignFingerprint(changed.bundle);expect(fingerprint).toBe(expected);
  changed.design_fingerprint=fingerprint;
  expect(runDesignBasis(changed,{...changed.bundle.simulation_runs[0],design_fingerprint:expected})).toBe("current");
 }
 const changed=structuredClone(bundle);changed.scene.pv_fields[0].tilt_deg+=1;
 expect(demoDesignFingerprint(changed)).not.toBe(expected);
});
