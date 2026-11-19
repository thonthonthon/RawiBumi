import { beforeEach, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
import type { Entity } from "../../src/state/store";
const h=vi.hoisted(()=>({ slots:[] as unknown[], cursor:0, resize:vi.fn(), store:{} as any }));
vi.mock("react",async(load)=>({...await load<typeof import("react")>(),useMemo:(f:()=>unknown)=>f(),useState:(initial:unknown)=>{const i=h.cursor++;if(!(i in h.slots))h.slots[i]=initial;return[h.slots[i],(v:unknown)=>{h.slots[i]=v;}];}}));
vi.mock("react-i18next",()=>({useTranslation:()=>({t:(key:string)=>key}),initReactI18next:{type:"3rdParty",init(){}}}));
vi.mock("../../src/state/store",()=>({useUI:(selector:(s:unknown)=>unknown)=>selector(h.store),useActions:()=>({dispatch:vi.fn(),toast:vi.fn()})}));
vi.mock("../../src/canvas/useEntityEdits",()=>({useEntityEdits:()=>({resize:h.resize})}));
vi.mock("../../src/state/history",()=>({engineCommand:vi.fn(),undo:vi.fn(),redo:vi.fn()}));
import { Inspector } from "../../src/Inspector";
import { Button, NumberInput, Field } from "../../src/ui/kit";
function tree(value:unknown):ReactElement<any>[] {if(Array.isArray(value))return value.flatMap(tree);if(!isValidElement(value))return[];const n=value as ReactElement<any>;return[n,...tree(n.props.children)];}
function render(){h.cursor=0;const root=Inspector();const child=tree(root).find((n)=>typeof n.type==="function"&&(n.type as Function).name==="EntityInspector")!;return tree((child.type as Function)(child.props));}
beforeEach(()=>{h.slots=[];h.resize.mockReset();const e:Entity={id:"roof",name:"Roof",kind:"surface",subtype:"flat_roof",polygon:[[0,0],[10,0],[0,4]],holes:[],plane:{mode:"flat",z_m:0},height_m:0,source:"engine",modified:false,pending:[],locked:false,hostsPvField:true};h.store={selection:["roof"],entities:[e],modules:[],view:{bundle:{project:{project_revision:{revision_number:1}},scene:{pv_fields:[]}}},busy:null};});
it("Inspector Resize 80% sends factor .8 and the bounding-box centre, not the triangle centroid",()=>{
 let nodes=render();const field=nodes.find((n)=>n.type===Field&&n.props.label==="Resize")!;tree(field.props.children).find((n)=>n.type===NumberInput)!.props.onChange(80);
 nodes=render();nodes.find((n)=>n.type===Button&&n.props.children==="Resize")!.props.onClick();expect(h.resize).toHaveBeenCalledWith(h.store.entities[0],[5,2],.8);
});
it("Resize visibly refuses busy or modified engine entities",()=>{h.store.busy="Saving";expect(render().find((n)=>n.type===Button&&n.props.children==="Resize")!.props.disabled).toBe(true);h.store.busy=null;h.store.entities[0].modified=true;expect(render().find((n)=>n.type===Button&&n.props.children==="Resize")!.props.disabled).toBe(true);});
