PVObject_=pvModule
  Version=6.81
  Flags=$00100043

  PVObject_Commercial=pvCommercial
    Comment=SGS-CSTC Standards Technical Service Co., Ltd
    Flags=$0041
    Manufacturer=Jinkosolar
    Model=JKM550M-72HL4-V
    DataSource=Manufacturer 2020 SGS-CSTC
    YearBeg=2020
    Width=1.134
    Height=2.278
    Depth=0.035
    Weight=28.000
    NPieces=100
    PriceDate=15/10/18 06:18
  End of PVObject pvCommercial

  Technol=mtSiMono
  NCelS=72
  NCelP=2
  NDiode=3
  GRef=1000
  TRef=25.0
  PNom=550.0
  PNomTolLow=0.00
  PNomTolUp=3.00
  Isc=14.030
  Voc=49.62
  Imp=13.450
  Vmp=40.90
  muISC=6.57
  muVocSpec=-137.9
  muPmpReq=-0.345
  RShunt=1100
  Rp_0=9000
  Rp_Exp=3.60
  RSerie=0.238
  Gamma=0.969
  muGamma=-0.0003
  VMaxIEC=1500
  VMaxUL=1500
  Absorb=0.90
  ARev=25.968
  BRev=10.356
  RDiode=0.010
  VRevDiode=-0.70
  AirMassRef=1.500
  CellArea=165.1
  SandiaAMCorr=50.000

  PVObject_IAM=pvIAM
    Flags=$00
    IAMMode=UserProfile
    IAMProfile=TCubicProfile
      NPtsMax=9
      NPtsEff=9
      LastCompile=$B18D
      Mode=3
      Point_1=0.0,1.00000
      Point_2=30.0,1.00000
      Point_3=50.0,1.00000
      Point_4=60.0,0.99900
      Point_5=70.0,0.98800
      Point_6=75.0,0.96500
      Point_7=80.0,0.92500
      Point_8=85.0,0.74300
      Point_9=90.0,0.00000
    End of TCubicProfile
  End of PVObject pvIAM
End of PVObject pvModule
