"""Reproducible local D-efficient MNL pilot design, with opt-out in information.

No respondent data or synchronization modules are imported. Zero priors are
explicit design assumptions, not estimates. NumPy/SciPy needed only to regenerate.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import csv
import itertools as it
import json
import hashlib
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SEED=20261025
PRICES=(15,24,34)
PROFILES=np.array(list(it.product((0,1),(0,1),(0,1),PRICES)),dtype=float)
ALL_PAIRS=list(it.combinations(range(24),2))

def dominates(a,b,origin_sign):
    x=PROFILES[a]*np.array([origin_sign,1,1,-1]);y=PROFILES[b]*np.array([origin_sign,1,1,-1])
    return bool(np.all(x>=y) and np.any(x>y))

PAIRS=[p for p in ALL_PAIRS if not any(dominates(*p,z) or dominates(*p[::-1],z) for z in (-1,1))]

def model_names(categorical=True,interactions=True,position=False):
    result=['origin','environment','quality']+(['price_24','price_34'] if categorical else ['price_per_10_yuan'])+['opt_out_asc']
    if interactions:result+=['environment_x_visual','environment_x_ai','environment_x_visual_ai','opt_out_x_visual','opt_out_x_ai','opt_out_x_visual_ai']
    if position:result+=['display_A_asc']
    return result

def matrix(pair,g,swap,categorical=True,interactions=True,position=False):
    v,ai=g;rows=[]
    for index in (pair[::-1] if swap else pair):
        o,e,q,p=PROFILES[index]
        row=[o-.5,e-.5,q-.5]+([float(p==24),float(p==34)] if categorical else [(p-24)/10])+[0.]
        if interactions:row += [(e-.5)*v,(e-.5)*ai,(e-.5)*v*ai,0.,0.,0.]
        rows.append(row)
    row=[0.]*(len(rows[0])-1)+[1.]
    if interactions:
        row=[0.]*(len(rows[0])-6);row[-1]=1.;row += [0.,0.,0.,v,ai,v*ai]
    rows.append(row)
    if position:
        for i,row in enumerate(rows):row.append(float(i==0))
    return np.asarray(rows)

def probabilities(pair,g,swap,prior):
    v,ai=g;u=[]
    for i in (pair[::-1] if swap else pair):
        o,e,q,p=PROFILES[i]
        u.append(prior.get('origin',0)*(o-.5)+(prior.get('environment',0)+prior.get('env_v',0)*v+prior.get('env_ai',0)*ai+prior.get('env_vai',0)*v*ai)*(e-.5)+prior.get('quality',0)*(q-.5)+prior.get('price10',0)*(p-24)/10)
    u.append(prior.get('opt_out',0));u=np.asarray(u);ex=np.exp(u-u.max());return ex/ex.sum()

def information(pairs,categorical=True,interactions=True,position=False,prior=None):
    prior=prior or {};p=len(model_names(categorical,interactions,position));out=[]
    for pair in pairs:
        m=np.zeros((p,p))
        for g in it.product((-.5,.5),repeat=2):
            for swap in (0,1):
                x=matrix(pair,g,swap,categorical,interactions,position);prob=probabilities(pair,g,swap,prior)
                m+=x.T@(np.diag(prob)-np.outer(prob,prob))@x/8
        out.append(m)
    return np.asarray(out)

def approximate(infos,tol=1e-6,max_iter=40000):
    n,p,_=infos.shape;w=np.full(n,1/n)
    for iteration in range(max_iter):
        m=np.einsum('i,ijk->jk',w,infos);inv=np.linalg.inv(m);deriv=np.einsum('ij,kji->k',inv,infos)
        gap=float(deriv.max()-p)
        if gap<tol:break
        w*=deriv/p;w/=w.sum()
    logdet=float(np.linalg.slogdet(m)[1])
    return dict(logdet=logdet,logdet_upper=logdet+max(gap,0),equivalence_gap=gap,iterations=iteration+1,information_matrix=m.tolist(),full_weights=w.tolist(),
                weights=[dict(pair=list(PAIRS[i]) if len(infos)==len(PAIRS) else list(ALL_PAIRS[i]),weight=float(x)) for i,x in enumerate(w) if x>1e-5])

def exact(infos,n=16,starts=160):
    rng=np.random.default_rng(SEED+n);p=infos.shape[1];found=[]
    for start in range(starts):
        chosen=rng.choice(len(infos),n,replace=False);total=infos[chosen].sum(axis=0)
        for sweep in range(60):
            changed=False
            for pos in rng.permutation(n):
                candidates=total-infos[chosen[pos]]+infos
                signs,values=np.linalg.slogdet(candidates)
                values[signs<=0]=-np.inf
                values[[int(x) for j,x in enumerate(chosen) if j!=pos]]=-np.inf
                best=int(values.argmax())
                if values[best]>np.linalg.slogdet(total)[1]+1e-10:
                    total=candidates[best];chosen[pos]=best;changed=True
            if not changed:break
        score=float(np.linalg.slogdet(total/n)[1]);found.append((score,chosen.copy()))
    found.sort(key=lambda x:-x[0])
    return found

def block_partition(chosen,infos):
    n=len(chosen);half=n//2;best=None
    raw=PROFILES[np.array([PAIRS[x] for x in chosen]).flatten()]
    for comb in it.combinations(range(1,n),half-1):
        left=np.asarray((0,*comb));right=np.asarray([i for i in range(n) if i not in left])
        imbalances=[]
        for indices in (left,right):
            x=raw[np.ravel(np.column_stack((2*indices,2*indices+1)))]
            imbalances.extend(abs(x[:,:3].sum(axis=0)-half))
            imbalances.extend(abs(np.array([(x[:,3]==p).sum() for p in PRICES])-2*half/3))
        ma=infos[chosen[left]].mean(axis=0);mb=infos[chosen[right]].mean(axis=0)
        sa,la=np.linalg.slogdet(ma);sb,lb=np.linalg.slogdet(mb)
        if sa<=0 or sb<=0:continue
        score=(min(la,lb),-sum(imbalances),la+lb)
        # Balance is a block allocation tie-break, not a replacement for D-error.
        if best is None or score>best[0]:best=(score,left,right)
    return best

def metrics(infos,chosen,names):
    m=infos[chosen].mean(axis=0);eigs=np.linalg.eigvalsh(m);p=len(names)
    rank=int(np.linalg.matrix_rank(m,tol=1e-10));logdet=float(np.linalg.slogdet(m)[1])
    return dict(parameters=names,rank=rank,dimension=p,d_error=float(np.exp(-logdet/p)),
                logdet=logdet,smallest_eigenvalue=float(eigs[0]),condition_number=float(np.linalg.cond(m)),
                se_if_800_respondents_8_tasks=dict(zip(names,np.sqrt(np.diag(np.linalg.inv(m)/6400)).tolist())),
                information_matrix=m.tolist())

def write_csv(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    out=ROOT/'docs'/'design_v2';out.mkdir(parents=True,exist_ok=True)
    infos=information(PAIRS);reference=approximate(infos);fullref=approximate(information(ALL_PAIRS))
    found=exact(infos);best_global=found[0][0]
    chosen=found[0][1];partition=block_partition(chosen,infos)
    for score,alternative in found[1:20]:
        if np.exp((score-best_global)/infos.shape[1])<.999:continue
        candidate=block_partition(alternative,infos)
        if candidate[0]>partition[0]:chosen=alternative;partition=candidate
    _,left,right=partition
    oriented=[];task_rows=[];tasks=[]
    # Base labels balanced by deterministic orientation search; actual delivery
    # retains independent 50:50 A/B swaps for every participant and task.
    selected_pairs=[PAIRS[i] for i in chosen]
    best_orientation=None
    for bits in it.product((0,1),repeat=16):
        a=np.array([PROFILES[p[b]] for p,b in zip(selected_pairs,bits)]);b=np.array([PROFILES[p[1-z]] for p,z in zip(selected_pairs,bits)])
        score=float(np.abs(a[:,:3].sum(0)-b[:,:3].sum(0)).sum()+sum(abs((a[:,3]==v).sum()-(b[:,3]==v).sum()) for v in PRICES))
        if best_orientation is None or score<best_orientation[0]:best_orientation=(score,bits)
        if score==0:break
    for block,indices in (('A',left),('B',right)):
        for seq,index in enumerate(indices,1):
            pair=selected_pairs[index];swap=best_orientation[1][index];raws=[PROFILES[pair[swap]],PROFILES[pair[1-swap]]]
            def offer(v):return dict(origin=int(v[0]),verification=int(v[1]),quality=int(v[2]),price=int(v[3]),price_level=PRICES.index(int(v[3]))+1,product_volume_ml=1000)
            tid=f'V2T{len(tasks)+1:02d}';tasks.append(dict(id=tid,block=block,seq=seq,a=offer(raws[0]),b=offer(raws[1])))
            task_rows.append(dict(task_id=tid,block=block,**{f'{label}_{k}':v for label,o in (('A',tasks[-1]['a']),('B',tasks[-1]['b'])) for k,v in o.items()}))
    target=ROOT/'designs'/'tasks_1l_v2.json';target.write_text(json.dumps(tasks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    base=metrics(infos,chosen,model_names());linear=metrics(information(PAIRS,categorical=False),chosen,model_names(False))
    sensitivity=[]
    for label,prior in [('zero',{}),('moderate',dict(origin=.2,environment=.5,quality=.4,price10=-.5,opt_out=0)),('strong_price',dict(origin=-.2,environment=.7,quality=.6,price10=-1.5,opt_out=.2,env_v=.2,env_ai=-.2,env_vai=.1))]:
        inf=information(PAIRS,prior=prior);ref=approximate(inf,tol=1e-5);met=metrics(inf,chosen,model_names())
        sensitivity.append(dict(scenario=label,assumed_parameters=prior,**met,relative_efficiency_bound=float(np.exp((met['logdet']-ref['logdet_upper'])/len(model_names())))))
    flat=[t[l] for t in tasks for l in ('a','b')];level_counts={}
    for block in ('all','A','B'):
        rows=[t[l] for t in tasks if block=='all' or t['block']==block for l in ('a','b')]
        level_counts[block]={k:{str(v):sum(o[k]==v for o in rows) for v in ((0,1) if k!='price' else PRICES)} for k in ('origin','verification','quality','price')}
    raw=np.array([[o[k] for k in ('origin','verification','quality','price')] for o in flat]);diff=np.array([[t['a'][k]-t['b'][k] for k in ('origin','verification','quality','price')] for t in tasks])
    validation=dict(profile_count=24,all_candidate_pairs=len(ALL_PAIRS),eligible_pairs=len(PAIRS),conditional_dominance_rejected=len(ALL_PAIRS)-len(PAIRS),
                    selected_conditional_dominance_count=sum(any(dominates(*p,z) or dominates(*p[::-1],z) for z in (-1,1)) for p in selected_pairs),
                    unique_selected_pairs=len(set(chosen.tolist())),unique_profiles_used=len({x for p in selected_pairs for x in p}),
                    level_counts=level_counts,raw_profile_correlations=np.corrcoef(raw,rowvar=False).tolist(),ab_difference_correlations=np.corrcoef(diff,rowvar=False).tolist(),
                    base_A_B_balance_score=best_orientation[0],display_swap_probability=.5)
    report=dict(version='study2-1l-3price-v2',seed=SEED,status='candidate_not_approved',task_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                optimization=dict(method='multistart exact coordinate exchange; categorical-price MNL local D-optimality at zero priors; opt-out and condition interactions included',starts=len(found),best_unblocked_logdet=best_global,
                                  selected_efficiency_vs_best_restart=float(np.exp((base['logdet']-best_global)/len(model_names())))),
                primary=base,linear_price=linear,position_augmented=metrics(information(PAIRS,position=True),chosen,model_names(position=True)),
                restricted_continuous_reference=reference,full_continuous_reference=fullref,
                d_efficiency_lower_bound_restricted=float(np.exp((base['logdet']-reference['logdet_upper'])/len(model_names()))),
                d_efficiency_lower_bound_all_pairs=float(np.exp((base['logdet']-fullref['logdet_upper'])/len(model_names()))),
                blocks={b:metrics(infos,chosen[indices],model_names()) for b,indices in (('A',left),('B',right))},
                block_main_models={b:metrics(information(PAIRS,interactions=False),chosen[indices],model_names(interactions=False)) for b,indices in (('A',left),('B',right))},
                validation=validation,sensitivity=sensitivity,
                assumptions=['Zero priors are not participant estimates. Price optimized categorically to retain all three levels.','Four advertising groups and both blocks assumed balanced, independent 50:50 display swaps.','Dominance is conditional on both signs for origin, weakly preferred information, and negative price; no factual safety/environment claim.','MNL Fisher efficiency is not a mixed-logit optimality certificate or sample-size/power proof.'])
    (out/'diagnostics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    write_csv(out/'choice_tasks.csv',task_rows)
    write_csv(out/'candidate_profiles.csv',[dict(profile_id=f'P{i+1:02d}',**{k:int(v) for k,v in zip(('origin','verification','quality','price_yuan'),p)},product_volume_ml=1000,price_level=PRICES.index(int(p[3]))+1) for i,p in enumerate(PROFILES)])
    print(json.dumps(dict(primary_rank=base['rank'],parameters=base['dimension'],D_error=base['d_error'],efficiency_lower_bound=report['d_efficiency_lower_bound_restricted'],all_pairs_efficiency=report['d_efficiency_lower_bound_all_pairs'],level_counts=level_counts,block_ranks={k:v['rank'] for k,v in report['blocks'].items()}),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
