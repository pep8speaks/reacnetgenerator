#!/usr/bin/env python3
# -*- coding: UTF-8 -*-  
# version 1.1.4
# updated at 2018/6/10 2:00
#########  Usage #########
## import getmo
## getmo.run()
## getmo.draw()
##########################
######### import #########
import time
import os
import gc
import math
from multiprocessing import Pool, Semaphore
import numpy as np
from functools import reduce
import itertools
try:
    from hmmlearn import hmm
except ImportError as e:
    print(e)
try:
    import networkx as nx
    import networkx.algorithms.isomorphism as iso
except ImportError as e:
    print(e)
try:
    import matplotlib as mpl
    mpl.use('Agg')
    import matplotlib.pyplot as plt
except ImportError as e:
    print(e)
try:
    from rdkit import Chem
    from rdkit.Chem import Draw
except ImportError as e:
    print(e)
######## function ########
def printtime(timearray):
    timearray.append(time.time())
    if len(timearray)>1:
       print("Step ",len(timearray)-1," has been completed. Time consumed: ",round(timearray[-1]-timearray[-2],3),"s")
    return timearray

def union_dict(x,y):  
    for k, v in y.items():
        if k in x.keys():
            x[k] += v
        else:
            x[k] = v
    return  x
    
def mo(i,bond,level,molecule,done,bondlist): #connect molecule
    molecule.append(i)
    done[i]=True
    for j in range(len(bond[i])):
        b=bond[i][j]
        l=level[i][j]
        bo=(i,b,l) if i<b else (b,i,l)
        if not bo in bondlist:
            bondlist.append(bo)
        if not done[b]:
            molecule,done,bondlist=mo(b,bond,level,molecule,done,bondlist)
    return molecule,done,bondlist

def readinputfile(readNfunc,readstepfunc,inputfilename,moleculetempfilename,stepinterval):
    N,atomtype,steplinenum=readNfunc(inputfilename)
    step,timestep=getdandtimestep(readstepfunc,N,steplinenum,inputfilename,stepinterval,moleculetempfilename)
    return N,atomtype,step,timestep
    
def readlammpsbondN(bondfilename):
    with open(bondfilename) as file:
        iscompleted=False
        for index,line in enumerate(file):
            if line.startswith("#"):
                if line.startswith("# Number of particles"):
                    if iscompleted:
                        stepbindex=index
                        break
                    else:
                        iscompleted=True
                        stepaindex=index
                    N=[int(s) for s in line.split() if s.isdigit()][0]
                    atomtype=np.zeros(N+1,dtype=np.int)
            else:
                s=line.split()
                atomtype[int(s[0])]=int(s[1])    
    steplinenum=stepbindex-stepaindex
    return N,atomtype,steplinenum

def readlammpsbondstep(item):
    element,N=item
    step,lines=element
    bond=[[] for x in range(N+1)]
    level=[[] for x in range(N+1)]
    for line in lines:
        if line:
            if line.startswith("#"):
                if line.startswith("# Timestep"):
                    timestep=step,[int(s) for s in line.split() if s.isdigit()][0]    
            else:  
                s=line.split()
                for i in range(int(s[2])):
                    bond[int(s[0])].append(int(s[i+3]))
                    bondlevel=round(float(s[i+4+int(s[2])]))
                    if bondlevel==0:
                        bondlevel=1
                    level[int(s[0])].append(bondlevel)     
    d=connectmolecule(N,{},step,bond,level)
    return d,timestep

def readlammpscrdN(crdfilename):
    with open(crdfilename) as f:
        iscompleted=False
        for index,line in enumerate(f):
            if line.startswith("ITEM:"):
                if line.startswith("ITEM: TIMESTEP"):
                    linecontent=4
                elif line.startswith("ITEM: ATOMS"):
                    linecontent=3
                elif line.startswith("ITEM: NUMBER OF ATOMS"):
                    linecontent=1
                elif line.startswith("ITEM: BOX BOUNDS"):
                    linecontent=2
            else:
                if linecontent==1:
                    if iscompleted:
                        stepbindex=index
                        break
                    else:
                        iscompleted=True
                        stepaindex=index
                    N=int(line.split()[0])
                    atomtype=np.zeros(N+1,dtype=np.int)
                elif linecontent==3:
                    s=line.split()
                    atomtype[int(s[0])]=int(s[1])
    steplinenum=stepbindex-stepaindex
    return N,atomtype,steplinenum

def readlammpscrdstep(item):
    element,N=item
    step,lines=element
    atomtype=np.zeros((N,1),dtype=np.int)
    atomcrd=np.zeros((N,3))
    for line in lines:
        if line:
            if line.startswith("ITEM:"):
                if line.startswith("ITEM: TIMESTEP"):
                    linecontent=4
                elif line.startswith("ITEM: ATOMS"):
                    linecontent=3
                elif line.startswith("ITEM: NUMBER OF ATOMS"):
                    linecontent=1
                elif line.startswith("ITEM: BOX BOUNDS"):
                    linecontent=2
            else:
                if linecontent==3:
                    s=line.split()
                    atomtype[int(s[0])-1]=int(s[1])
                    atomcrd[int(s[0])-1]=float(s[2]),float(s[3]),float(s[4])
                elif linecontent==4:
                    timestep=step,int(line.split()[0])
    bond,level=getbondfromcrd(atomtype,atomcrd,step)
    d=connectmolecule(N,{},step,bond,level)
    return d,timestep

def getdandtimestep(readfunc,N,steplinenum,filename,stepinterval,moleculetempfilename):
    d={} 
    timestep={}
    with open(filename) as file,Pool(maxtasksperchild=100) as pool:
        semaphore = Semaphore(360)
        results=pool.imap_unordered(readfunc,produce(semaphore,enumerate(itertools.islice(itertools.zip_longest(*[file]*steplinenum),0,None,stepinterval)),N),10)
        for dstep,timesteptuple in results:
            d=union_dict(d,dstep)
            step,thetimestep=timesteptuple
            timestep[step]=thetimestep
            semaphore.release()
    writemoleculetempfile(moleculetempfilename,d)
    step=len(timestep)-1   
    return step,timestep
    
def connectmolecule(N,d,step,bond,level):
    #init
    done=np.zeros(N+1,dtype=bool)
    #connect molecule
    for i in range(1,N+1):
        if not done[i]:
            mole,done,bondlist=mo(i,bond,level,[],done,[])
            mole.sort()
            bondlist.sort()
            if (tuple(mole),tuple(bondlist)) in d:
                d[(tuple(mole),tuple(bondlist))].append(step)
            else:
                d[(tuple(mole),tuple(bondlist))]=[step]
    return d
    
def writemoleculetempfile(moleculetempfilename,d):
    with open(moleculetempfilename,'w') as f:
        for item in d.items():
            key,value=item
            print(",".join([str(x) for x in key[0]]),";".join([",".join([str(y) for y in x]) for x in key[1]]),",".join([str(x) for x in value]),file=f)
    
def getbondfromcrd(atomtype,atomcrd,step,filename="crd"):  
    xyzfilename=filename+"_"+str(step)+".xyz"
    mol2filename=filename+"_"+str(step)+".mol2"
    convertxyz(atomtype,atomcrd,xyzfilename)
    os.system("obabel -ixyz "+xyzfilename+" -omol2 -O "+mol2filename+" >/dev/null")
    bond,bondlevel=getbondfrommol2(len(atomcrd),mol2filename)
    return bond,bondlevel

def convertxyz(atomtype,atomcrd,xyzfilename):
    with open(xyzfilename,'w') as f:
        print(len(atomcrd),file=f)
        print("by getmo.py",file=f)
        for type,(x,y,z) in zip(atomtype,atomcrd): 
            print(["C","H","O"][type-1],x,y,z,file=f)

def getbondfrommol2(atomnumber,mol2filename):
    linecontent=-1
    bond=[[] for i in range(atomnumber+1)]
    bondlevel=[[] for i in range(atomnumber+1)]
    with open(mol2filename) as f:
        for line in f:
            if line.startswith("@<TRIPOS>BOND"):
                linecontent=0
            else:
                if linecontent==0:
                    s=line.split()
                    bond[int(s[1])].append(int(s[2]))
                    bond[int(s[2])].append(int(s[1]))
                    level=12 if s[3]=='ar' else int(s[3])
                    bondlevel[int(s[1])].append(level)
                    bondlevel[int(s[2])].append(level)
    return bond,bondlevel

def initHMM(states,observations,p,a,b):
    n_states = len(states)
    n_observations = len(observations)
    model = hmm.MultinomialHMM(n_components=n_states)
    model.startprob_= np.array(p)
    model.transmat_= np.array(a)
    model.emissionprob_= np.array(b)
    return model

def gethmm(ori,model,states):
    o = np.array([ori]).T
    logprob, h = model.decode(o, algorithm="viterbi")
    hmmlist=list(map(lambda x: states[x], h))
    return hmmlist
            
def produce(semaphore, list,parameter):
    for item in list:
        # Reduce Semaphore by 1 or wait if 0
        semaphore.acquire()
        # Now deliver an item to the caller (pool)
        yield item,parameter

def getoriginandhmm(item):
    line,parameter=item
    step,model,states=parameter
    list=line.split()
    value=np.array([int(x)-1 for x in list[-1].split(",")])
    origin=np.zeros(step,dtype=np.int)
    origin[value]=1
    hmm=gethmm(origin,model,states)
    return origin,hmm,line

def calhmm(originfilename,hmmfilename,moleculetempfilename,moleculetemp2filename,model,states,step,getoriginfile,printfiltersignal):
    with open(originfilename, 'w') as fo,open(hmmfilename, 'w') as fh,open(moleculetempfilename) as ft,open(moleculetemp2filename,'w') as ft2,Pool(maxtasksperchild=100) as pool:
        semaphore = Semaphore(360)
        results=pool.imap_unordered(getoriginandhmm,produce(semaphore,ft,(step,model,states)),10)
        for originsignal,hmmsignal,mlist in results:
            if 1 in hmmsignal or printfiltersignal:
                if getoriginfile:
                    print("".join([str(i) for i in originsignal]), file=fo)
                print("".join([str(i) for i in hmmsignal]), file=fh)
                print(mlist,end='',file=ft2)
            semaphore.release()
     
def getorigin(item):
    line,parameter=item
    step,=parameter
    list=line.split()
    value=np.array([int(x) for x in list[-1].split(",")])
    origin=np.zeros(step,dtype=np.int)
    origin[value]=1
    return origin,line     
         
def noHMM(originfilename,moleculetempfilename,moleculetemp2filename,step):
    with open(originfilename, 'w') as fh,open(moleculetempfilename) as ft,open(moleculetemp2filename,'w') as ft2,Pool(maxtasksperchild=100) as pool:
        semaphore = Semaphore(360)
        results=pool.imap_unordered(getorigin,produce(semaphore,ft,(step,)),10)
        for originsignal,mlist in results:
            print("".join([str(i) for i in originsignal]), file=fh)
            print(mlist,end='',file=ft2)
            semaphore.release()

def getatomroute(item):
    itemi,parameter=item
    i,(atomeachi,atomtypei)=itemi
    step,atomname,mname,timestep=parameter
    route=[]
    routestrarr=[]
    moleculeroute=[]
    molecule=-1
    right=-1
    for j in range(0,step):
        if atomeachi[j]>0 and atomeachi[j]!=molecule:
            routestrarr.append(mname[atomeachi[j]-1] + " ("+ str(atomeachi[j])+" step "+str(timestep[j])+")")
            left=right
            molecule=atomeachi[j]
            right=molecule
            if left>=0 and not (left,right) in moleculeroute:
                moleculeroute.append((left,right))
    routestr="Atom "+str(i)+" "+atomname[atomtypei-1]+": "+" -> ".join(routestrarr)
    return moleculeroute,routestr

def printatomroute(atomroutefilename,N,step,atomeach,atomtype,atomname,mname,timestep):
    with open(atomroutefilename, 'w') as f,Pool(maxtasksperchild=100) as pool:
        allmoleculeroute=[]
        semaphore = Semaphore(360)
        results=pool.imap(getatomroute,produce(semaphore,enumerate(zip(atomeach[1:],atomtype[1:]),start=1),(step,atomname,mname,timestep)),10)
        for route in results:
            moleculeroute,routestr=route
            print(routestr, file=f)
            for mroute in moleculeroute:
                if not mroute in allmoleculeroute:
                    allmoleculeroute.append(mroute)
            semaphore.release() 
    return allmoleculeroute

def makemoleculegraph(atoms,bonds):
    G=nx.Graph()
    for line in bonds:
        G.add_edge(line[0],line[1],level=line[2])
    for atom in atoms:
        atomnumber,atomtype=atom
        G.add_node(atomnumber, atom=atomtype)
    return G

def getstructure(name,atoms,bonds,atomtype,atomname):
    index={}
    for i,atom in enumerate(atoms,start=1):
        index[atom]=i
    return name+" "+",".join([atomname[atomtype[x]-1] for x in atoms])+" "+";".join([str(index[x[0]])+","+str(index[x[1]])+","+str(x[2]) for x in bonds])

def readstrcture(moleculestructurefilename):
    with open(moleculestructurefilename) as f:
        d={}
        for line in f:
            list=line.split()
            name=list[0]
            atoms=[x for x in list[1].split(",")]
            bonds=[tuple(int(y) for y in x.split(",")) for x in list[2].split(";")] if len(list)==3 else []
            d[name]=(atoms,bonds)
    return d

def printmoleculename(moleculefilename,moleculetempfilename,moleculestructurefilename,atomname,atomtype):
    mname=[]
    d={}
    em = iso.numerical_edge_match(['atom','level'], ["None",1])
    with open(moleculefilename, 'w') as fm,open(moleculetempfilename) as ft,open(moleculestructurefilename,'w') as fs:
        for line in ft:
            list=line.split()
            atoms=np.array([int(x) for x in list[0].split(",")])
            bonds=np.array([tuple(int(y) for y in x.split(",")) for x in list[1].split(";")] if len(list)==3 else [])
            typenumber=np.zeros(len(atomname),dtype=np.int)
            atomtypes=[]
            for atomnumber in atoms:
                typenumber[atomtype[atomnumber]-1]+=1
                atomtypes.append((atomnumber,atomtype[atomnumber]))
            G=makemoleculegraph(atomtypes,bonds)
            name="".join([atomname[i]+(str(typenumber[i] if typenumber[i]>1 else "")) if typenumber[i]>0 else "" for i in range(0,len(atomname))])                
            if name in d:
                for j in range(len(d[name])):
                    if nx.is_isomorphic(G,d[name][j],em):
                        if j>0:
                            name+="_"+str(j+1)
                        break
                else:
                    d[name].append(G)
                    name+="_"+str(len(d[name]))
                    print(getstructure(name,atoms,bonds,atomtype,atomname),file=fs)
            else:
                d[name]=[G]
                print(getstructure(name,atoms,bonds,atomtype,atomname),file=fs)
            mname.append(name)
            print(name,atoms,bonds, file=fm)
    return mname

def calmoleculeSMILESname(item):
    line,parameter=item
    list=line.split()
    atomname,atomtype=parameter
    atoms=np.array([int(x) for x in list[0].split(",")])
    bonds=np.array([tuple(int(y) for y in x.split(",")) for x in list[1].split(";")] if len(list)==3 else [])
    type={}
    for atomnumber in atoms:
        type[atomnumber]=atomname[atomtype[atomnumber]-1]
    name=convertSMILES(atoms,bonds,type)
    return name,atoms,bonds
    
def printmoleculeSMILESname(moleculefilename,moleculetempfilename,atomname,atomtype):
    mname=[]
    with open(moleculefilename, 'w') as fm,open(moleculetempfilename) as ft,Pool(maxtasksperchild=100) as pool:
        semaphore = Semaphore(360)
        results=pool.imap(calmoleculeSMILESname,produce(semaphore,ft,(atomname,atomtype)),10)
        for result in results:
            name,atoms,bonds=result
            mname.append(name)
            print(name,atoms,bonds,file=fm)
            semaphore.release()
    return mname
    
def convertSMILES(atoms,bonds,type):
    m = Chem.RWMol(Chem.MolFromSmiles(''))
    d={}
    for atomnumber in atoms:
        d[atomnumber]=m.AddAtom(Chem.Atom(type[atomnumber]))
    for bond in bonds:
        atom1,atom2,level=bond
        m.AddBond(d[atom1],d[atom2], Chem.BondType.DOUBLE if level==2 else (Chem.BondType.TRIPLE if level==3 else (Chem.BondType.AROMATIC if level==12 else Chem.BondType.SINGLE)))
    name=Chem.MolToSmiles(m)
    return name
    
def getatomeach(hmmfilename,moleculetemp2filename,atomfilename,N,step):
    atomeach=np.zeros((N+1,step),dtype=np.int)
    with open(hmmfilename) as fh,open(moleculetemp2filename) as ft:
        for i,(lineh,linet) in enumerate(zip(fh,ft),start=1):
            list=linet.split()
            key1=np.array([int(x) for x in list[0].split(",")])
            index=np.array([j for j in range(len(lineh)) if lineh[j]=="1"])
            atomeach[key1[:,None],index]=i
    with open(atomfilename, 'w') as f:
        for atom in atomeach[1:]:
            print(atom, file=f)
    return atomeach

def getallroute(reactionfilename,allmoleculeroute,mname):
    allroute={}
    for moleculeroute in allmoleculeroute:
        leftname=mname[moleculeroute[0]-1]
        rightname=mname[moleculeroute[1]-1]
        if leftname==rightname:
            continue
        equation=leftname+"->"+rightname
        if equation in allroute:
            allroute[equation]+=1
        else:
            allroute[equation]=1            
    return allroute

def printtable(tablefilename,reactionfilename,allroute):
    species=[]
    table=np.zeros((100,100),dtype=np.int)
    with open(reactionfilename,'w') as f:
        for k, v in sorted(allroute.items(), key=lambda d: d[1] ,reverse=True):
            print(v,k,file=f)
            left,right=k.split("->")
            for i,spec in enumerate([left,right]):
                if spec in species:
                    number=species.index(spec)    
                elif len(species)<100:
                    species.append(spec)
                    number=species.index(spec)
                else:
                    number=-1
                if i==0:
                    leftnumber=number
                else:
                    rightnumber=number
            if leftnumber>=0 and rightnumber>=0:
                table[leftnumber][rightnumber]=v
    with open(tablefilename,'w') as f:
        print("\t"+"\t".join(species),file=f)
        for i in range(len(species)):
            print(species[i],end='\t',file=f)
            for j in range(len(species)):
                print(table[i][j],end='\t',file=f)
            print(file=f)

def readtable(tablefilename):
    table=[]
    name=[]
    with open(tablefilename) as file:
        for line in itertools.islice(file, 1, None):
            name.append(line.split()[0])
            table.append([int(s) for s in line.split()[1:]])
    return table,name
    
def convertstructure(atoms,bonds,atomname):
    types={}
    atomtypes=[]
    for atom in enumerate(atoms,start=1):
        atomtypes.append((i,atomname.index(atom)))
    G=makemoleculegraph(atomtypes,bonds)
    return G
    
def handlespecies(species,name,maxspecies,atomname,moleculestructurefilename,showid):
    showname={}
    n=0
    if species=={}:
        species_out=dict([(x,{}) for x in (name if len(name)<=maxspecies else name[0:maxspecies])])
    else:
        species_out={}
        b=True
        for spec in species.items():
            specname,value=spec
            if "structure" in value:
                atoms,bonds=value["structure"]
                G1=convertstructure(atoms,bonds,atomname)
                if b:
                    structures=readstrcture(moleculestructurefilename)
                    em = iso.numerical_edge_match(['atom','level'], ["None",1])
                    b=False
                i=1
                while (specname+"_"+str(i) if i>1 else specname) in structures:
                    G2=convertstructure(structures[(specname+"_"+str(i) if i>1 else specname)][0],structures[(specname+"_"+str(i) if i>1 else specname)][1],atomname)
                    if nx.is_isomorphic(G1,G2,em):
                        if i>1:
                            specname+="_"+str(i)
                        break
                    i+=1
            species_out[specname]={}
            if "showname" in value:
                showname[specname]=value["showname"]
    if showid:
        for specname,value in species_out.items():
            n+=1
            showname[specname]=str(n)
            print(n,specname)
    return species_out,showname
    
######## steps ######
def step1(inputfiletype,inputfilename,moleculetempfilename,stepinterval):
    if inputfiletype=="lammpsbondfile":
        readNfunc=readlammpsbondN
        readstepfunc=readlammpsbondstep
    elif inputfiletype=="lammpscrdfile" or inputfiletype=="lammpsdumpfile":
        readNfunc=readlammpscrdN
        readstepfunc=readlammpscrdstep   
    N,atomtype,step,timestep=readinputfile(readNfunc,readstepfunc,inputfilename,moleculetempfilename,stepinterval)
    return N,atomtype,step,timestep
    
def step2(states,observations,p,a,b,originfilename,hmmfilename,moleculetempfilename,moleculetemp2filename,step,runHMM,getoriginfile,printfiltersignal):
    if runHMM:
        model=initHMM(states,observations,p,a,b)
        calhmm(originfilename,hmmfilename,moleculetempfilename,moleculetemp2filename,model,states,step,getoriginfile,printfiltersignal)
    else:
        noHMM(originfilename,moleculetempfilename,moleculetemp2filename,step)

def step3(atomname,atomtype,N,step,timestep,moleculefilename,hmmfilename,atomfilename,moleculetemp2filename,atomroutefilename,moleculestructurefilename,SMILES):
    if SMILES:
        mname=printmoleculeSMILESname(moleculefilename,moleculetemp2filename,atomname,atomtype)
    else:
        mname=printmoleculename(moleculefilename,moleculetemp2filename,moleculestructurefilename,atomname,atomtype)
    atomeach=getatomeach(hmmfilename,moleculetemp2filename,atomfilename,N,step)
    allmoleculeroute=printatomroute(atomroutefilename,N,step,atomeach,atomtype,atomname,mname,timestep)
    return allmoleculeroute,mname

def step4(allmoleculeroute,mname,reactionfilename,tablefilename):
    allroute=getallroute(reactionfilename,allmoleculeroute,mname)
    printtable(tablefilename,reactionfilename,allroute)
######## run ########
def run(inputfiletype="lammpsbondfile",inputfilename="bonds.reaxc",atomname=["C","H","O"],originfilename="originsignal.txt",hmmfilename="hmmsignal.txt",atomfilename="atom.txt",moleculefilename="moleculename.txt",atomroutefilename="atomroute.txt",reactionfilename="reaction.txt",tablefilename="table.txt",moleculetempfilename="moleculetemp.txt",moleculetemp2filename="moleculetemp2.txt",moleculestructurefilename="moleculestructure.txt",stepinterval=1,states=[0,1],observations=[0,1],p=[0.5,0.5],a=[[0.999,0.001],[0.001,0.999]],b=[[0.6, 0.4],[0.4, 0.6]],runHMM=True,getoriginfile=False,SMILES=True,printfiltersignal=False):
    ######### Parameter above ############
    ######start#####
    print("Run HMM calculation:")
    timearray=printtime([])
    for runstep in range(1,5):
        ######## step 1 ##### 
        if(runstep==1):
            N,atomtype,step,timestep=step1(inputfiletype,inputfilename,moleculetempfilename,stepinterval)
        ######## step 2 ##### 
        elif(runstep==2):
            step2(states,observations,p,a,b,originfilename,hmmfilename,moleculetempfilename,moleculetemp2filename,step,runHMM,getoriginfile,printfiltersignal)
        ######## step 3 ##### 
        elif(runstep==3):
            allmoleculeroute,mname=step3(atomname,atomtype,N,step,timestep,moleculefilename,hmmfilename if runHMM else originfilename,atomfilename,moleculetemp2filename,atomroutefilename,moleculestructurefilename,SMILES)
        ######## step 4 ##### 
        elif(runstep==4):
            step4(allmoleculeroute,mname,reactionfilename,tablefilename)
        #garbage collect
        gc.collect()
        timearray=printtime(timearray)
    ####### end #######
    print()
    print("Time consumed:")
    for i in range(1,len(timearray)):
        print("Step ",i," consumed: ",round(timearray[i]-timearray[i-1],3),"s")
    print("Total time:",round(timearray[-1]-timearray[0],3),"s")
    print()

#####draw#####    
def draw(tablefilename="table.txt",imagefilename="image.svg",moleculestructurefilename="moleculestructure.txt",species={},node_size=200,font_size=6,widthcoefficient=1,show=False,maxspecies=20,n_color=256,atomname=["C","H","O"],drawmolecule=False,nolabel=False,filter=[],node_color=[135/256,206/256,250/256],pos={},showid=True,k=None):
    #start
    print("Draw the image:")
    timearray=printtime([])
    #read table
    table,name=readtable(tablefilename)
    species,showname=handlespecies(species,name,maxspecies,atomname,moleculestructurefilename,showid)

    #make color
    start = np.array([1, 1, 0])
    end = np.array([1, 0, 0])
    colorsRGB=[(start + i*(end-start) / n_color) for i in range(n_color)]
          
    G = nx.DiGraph()
    for i in range(len(table)):
        if name[i] in species and not name[i] in filter:
            G.add_node(showname[name[i]] if name[i] in showname else name[i])
            for j in range(len(table)):
                if name[j] in species and not name[j] in filter:
                    if table[i][j]>0:
                        G.add_weighted_edges_from([((showname[name[i]] if name[i] in showname else name[i]),(showname[name[j]] if name[j] in showname else name[j]),table[i][j])])
    weights = np.array([math.log(G[u][v]['weight']) for u,v in G.edges()])
    widths=[weight/max(weights) *widthcoefficient for weight in weights]
    colors=[colorsRGB[math.floor(weight/max(weights)*(n_color-1))] for weight in weights]
    try:
        pos = (nx.spring_layout(G) if not pos else nx.spring_layout(G,pos=pos,fixed=[p for p in pos])) if not k else (nx.spring_layout(G,k=k) if not pos else nx.spring_layout(G,pos=pos,fixed=[p for p in pos],k=k))
        print(pos)
        
        for with_labels in ([True] if not nolabel else [True,False]):
            nx.draw(G,pos = pos,width=widths,node_size=node_size,font_size=font_size,with_labels=with_labels,edge_color=colors,node_color=np.array(node_color))

            plt.savefig(imagefilename if with_labels else "nolabel_"+imagefilename)
            
            if show:
                plt.show()
                
            plt.close()

    except Exception as e:
        print("Error: cannot draw images.",e)
    
    timearray=printtime(timearray)
    ####### end #######
    print()
    print("Time consumed:")
    for i in range(1,len(timearray)):
        print("Step ",i," consumed: ",round(timearray[i]-timearray[i-1],3),"s")
    print("Total time:",round(timearray[-1]-timearray[0],3),"s")
    print()
    return pos
#### run and draw ####
def runanddraw(inputfiletype="lammpsbondfile",inputfilename="bonds.reaxc",atomname=["C","H","O"],originfilename="originsignal.txt",hmmfilename="hmmsignal.txt",atomfilename="atom.txt",moleculefilename="moleculename.txt",atomroutefilename="atomroute.txt",reactionfilename="reaction.txt",tablefilename="table.txt",moleculetempfilename="moleculetemp.txt",moleculetemp2filename="moleculetemp2.txt",moleculestructurefilename="moleculestructure.txt",imagefilename="image.svg",stepinterval=1,states=[0,1],observations=[0,1],p=[0.5,0.5],a=[[0.999,0.001],[0.001,0.999]],b=[[0.6, 0.4],[0.4, 0.6]],runHMM=True,SMILES=True,getoriginfile=False,species={},node_size=200,font_size=6,widthcoefficient=1,show=False,maxspecies=20,n_color=256,drawmolecule=False,nolabel=False,filter=[],node_color=[135/256,206/256,250/256],pos={},printfiltersignal=False,showid=True,k=None):
    run(inputfiletype,inputfilename,atomname,originfilename,hmmfilename,atomfilename,moleculefilename,atomroutefilename,reactionfilename,tablefilename,moleculetempfilename,moleculetemp2filename,moleculestructurefilename,stepinterval,states,observations,p,a,b,runHMM,getoriginfile,SMILES,printfiltersignal)
    pos=draw(tablefilename,imagefilename,moleculestructurefilename,species,node_size,font_size,widthcoefficient,show,maxspecies,n_color,atomname,drawmolecule,nolabel,filter,node_color,pos,showid,k)
    return pos
##### main #####
if __name__ == '__main__':
    runanddraw()