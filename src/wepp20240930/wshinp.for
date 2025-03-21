      subroutine wshinp(jstruc)
c
c     + + + PURPOSE + + +
c
c     SR WSHINP reads the watershed structure and channel files
c     and performs rudimentary checks.
c
c     Called from: SR WSHDRV
c     Author(s): Ascough II
c     Reference in User Guide:
c
c     Version:
c     Date recoded:
c     Recoded by:
c
c     + + + KEYWORDS + + +
c
c     + + + PARAMETERS + + +
c
      include 'pmxcsg.inc'
      include 'pmxelm.inc'
      include 'pmxhil.inc'
      include 'pmximp.inc'
      include 'pmxnsl.inc'
      include 'pmxpln.inc'
      include 'pmxpnd.inc'
      include 'pmxprt.inc'
      include 'pmxslp.inc'
c Added by L. Wang, 8/28/2009.
      include 'pmxchr.inc'
c End adding.
c
c     + + + ARGUMENT DECLARATIONS + + +
c
      integer jstruc
c
c     + + + ARGUMENT DEFINITIONS + + +
c
c     jstruc - number of planes (channels) read in from the
c              management file
c
c     + + + COMMON BLOCKS + + +
c
      include 'cchpar.inc'
c     modify: ishape(mxplan),chnlen(mxplan),chnz(mxplan),
c             chnnbr(mxplan),ncsseg(mxplan),
c             chnx(mxplan,mxcseg),chnslp(mxplan,mxcseg),
c             chnwid(mxplan),flgout(mxplan)
c
      include 'cchpek.inc'
c     modify: ipeak
c
      include 'cchtrl.inc'
c     modify: icntrl(mxplan), ctlz(mxplan), ctln(mxplan),
c             ctlslp(mxplan), rccoef(mxplan),
c             rcexp(mxplan), rcoset(mxplan), ycntrl(mxplan),
c             ienslp(mxplan)
c
      include 'cchvar.inc'
c     modify: chnn(mxplan),chntcr(mxplan),chnedm(mxplan),
c             chneds(mxplan),chnk(mxplan)
c
      include 'cdist2.inc'
c     read: slplen(mxplan)
c
      include 'cimpnd.inc'
c     modify: ipd(mximp),npond
c
      include 'cparame.inc'
c     read: ks(mxplan)
c
      include 'cslope1.inc'
c     read: nslpts(mxplan)
c
      include 'csolva1.inc'
c     read: sand(mxnsl,mxelem), silt(mxnsl,mxelem),
c           clay(mxnsl,mxelem), orgmat(mxnsl,mxelem)
c
      include 'cslpopt.inc'
c     read: fwidth(mxplan)
c
      include 'cstruc.inc'
c     read: nhill
c
      include 'cstruct.inc'
c     modify: nchan,ich(0:mxplan),nelmt,idelmt(0:mxplan),
c             elmt(mxelem),nhleft(mxelem),nhrght(mxelem),
c             nhtop(mxelem),ncleft(mxelem),ncrght(mxelem),
c             nctop(mxelem),nileft(mxelem),nirght(mxelem),
c             nitop(mxelem), hill(0:mxelem)
c Added by L. Wang for channel routing, 08/20/2009.
      include 'cchrt.inc'
c End adding.
c
c     + + + LOCAL VARIABLES + + +
c
      integer chntmp, hiltmp, i, nhchk, nhmax
CAS Added by A. Srivastava 3/21/2016
      integer tcrflg
CAS End adding.
c
c     removed 10-9-2003 jrf
c     character*3 hildat(0:mxhill), chndat(0:mxplan), impdat(0:mximp)
      character*7 elmtyp(3)
c
c     + + + LOCAL DEFINITIONS + + +
c
c     chntmp - local variable for number of channels read in from
c              channel file
c     hiltmp - local variable for number of hillslopes read in from
c              hillslope/watershed pass file
c     i      - loop counter
c     nhchk  - counter for the maximum hillslope element read in
c              from the watershed structure file
c     nhmax  - the maximum hillslope element read in from the
c              watershed structure file
c     hildat(0:mxhill) -
c     chndat(0:mxplan) -
c     impdat(0:mximp) -
c     elmtyp(3) -
c
c     + + + SAVES + + +
c
c     + + + SUBROUTINES CALLED + + +
c
c     eatcom
c
c     + + + DATA INITIALIZATIONS + + +
c
      data elmtyp /'HILLSLP', 'CHANNEL', 'IMPOUND'/
c
c     changed 10-9-2003 - Jim Frankenberger
c         Calculate the hillslope, channel and impoundment names
c         directly to handle more hillslopes and channels
      character(len=6) :: hleftstr
      character(len=6) :: hrightstr
      character(len=6) :: htopstr
      character(len=6) :: cleftstr
      character(len=6) :: crightstr
      character(len=6) :: ctopstr
      character(len=6) :: ileftstr
      character(len=6) :: irightstr
      character(len=6) :: itopstr
c     removed following tables 10-9-2003 - jrf- now generated through code 
c        to handle more channels, hillslopes and impoundments
c      data hildat /'   ', 'H1 ', 'H2 ', 'H3 ', 'H4 ', 'H5 ', 'H6 ',
c     1    'H7 ', 'H8 ', 'H9 ', 'H10', 'H11', 'H12', 'H13', 'H14', 'H15',
c     1    'H16', 'H17', 'H18', 'H19', 'H20', 'H21', 'H22', 'H23', 'H24',
c     1    'H25', 'H26', 'H27', 'H28', 'H29', 'H30', 'H31', 'H32', 'H33',
c     1    'H34', 'H35', 'H36', 'H37', 'H38', 'H39', 'H40', 'H41', 'H42',
c     1    'H43', 'H44', 'H45', 'H46', 'H47', 'H48', 'H49', 'H50', 'H51',
c     1    'H52', 'H53', 'H54', 'H55', 'H56', 'H57', 'H58', 'H59', 'H60',
c     1    'H61', 'H62', 'H63', 'H64', 'H65', 'H66', 'H67', 'H68', 'H69',
c     1    'H70', 'H71', 'H72', 'H73', 'H74', 'H75'/
c
c      data chndat /'   ', 'C1 ', 'C2 ', 'C3 ', 'C4 ', 'C5 ', 'C6 ',
c     1    'C7 ', 'C8 ', 'C9 ', 'C10', 'C11', 'C12', 'C13', 'C14', 'C15',
c     1    'C16', 'C17', 'C18', 'C19', 'C20', 'C21', 'C22', 'C23', 'C24',
c     1    'C25', 'C26', 'C27', 'C28', 'C29', 'C30', 'C31', 'C32', 'C33',
c     1    'C34', 'C35', 'C36', 'C37', 'C38', 'C39', 'C40', 'C41', 'C42',
c     1    'C43', 'C44', 'C45', 'C46', 'C47', 'C48', 'C49', 'C50', 'C51',
c     1    'C52', 'C53', 'C54', 'C55', 'C56', 'C57', 'C58', 'C59', 'C60',
c     1    'C61', 'C62', 'C63', 'C64', 'C65', 'C66', 'C67', 'C68', 'C69',
c     1    'C70', 'C71', 'C72', 'C73', 'C74', 'C75'/
c
c      data impdat /'   ', 'I1 ', 'I2 ', 'I3 ', 'I4 ', 'I5 ', 'I6 ',
c     1    'I7 ', 'I8 ', 'I9 ', 'I10', 'I11', 'I12', 'I13', 'I14', 'I15',
c     1    'I16', 'I17', 'I18', 'I19', 'I20', 'I21', 'I22', 'I23', 'I24',
c     1    'I25'/
c
c     + + + END SPECIFICATIONS + + +
c
CAS Added by A. Srivastava 3/21/2016
CAS Flag to determine channel critical shear stress from channel slope.
      tcrflg = 0
      open(unit=66,file='tcr.txt',status='old',err=401)
      tcrflg = 1
      write(6,2800)
      close(66)
      goto 402
 401  tcrflg = 0     
 402  continue
CAS End adding.
c
c     read in number of hillslopes from hillslope/watershed pass file
c
      read (49,*) hiltmp
c
c     check #1 - # of hillslopes requested in main input must be less
c     than or equal to # hillslopes in the hillslope/watershed pass file
c
      if (nhill.gt.hiltmp) then
        write (6,1400) nhill, hiltmp
        stop
      end if
c
c     assign hillslope id variables
c
      idelmt(0) = 0
c
      do 10 i = 1, nhill
        idelmt(i) = i
        elmt(i) = 1
        hill(i) = 0
   10 continue
c
c     read in watershed structure file information
c
      nchan = 0
      npond = 0
      nhmax = 0
c
      write (38,1300) nhill
c
      ich(0) = 0
      ipd(0) = 0
      hill(0) = 0
c
      do 20 i = nhill + 1, mxelem
c
        read (17,*,end=30) elmt(i), nhleft(i), nhrght(i), nhtop(i),
     1      ncleft(i), ncrght(i), nctop(i), nileft(i), nirght(i),
     1      nitop(i)
c
        if (elmt(i).eq.2) then
          nchan = nchan + 1
          ich(nchan) = i
          idelmt(i) = nchan
          ieltyp(i) = 'channel    '
        else if (elmt(i).eq.3) then
          npond = npond + 1
          ipd(npond) = i
          idelmt(i) = npond
          ieltyp(i) = 'impoundment'
        end if
c
        nhchk = max0(nhleft(i),nhrght(i),nhtop(i))
        if (nhchk.gt.nhmax) nhmax = nhchk
c
c       check #2 --> each channel or impoundment element
c       must receive contributions either from the top or
c       laterally by a hillslope, channel, or impoundment
c
        if (((nhleft(i).eq.0).and.(nhrght(i).eq.0).and.(nhtop(i).eq.0))
     1      .and.(((ncleft(i).eq.0).and.(ncrght(i).eq.0).and.(nctop(i)
     1      .eq.0))).and.(((nileft(i).eq.0).and.(nirght(i).eq.0).and.(
     1      nitop(i).eq.0)))) then
          write (6,1500)
          stop
        end if
c
c       write out structure file information
c

        if (nhleft(i) > 0) then
           write (hleftstr,'(a,i0)') 'H',nhleft(i)
        else
           write (hleftstr,'(a)') '   '
        end if

        if (nhrght(i) > 0) then
           write(hrightstr,'(a,i0)') 'H',nhrght(i)
        else
           write(hrightstr,'(a)') '    '
        end if

        if (nhtop(i) > 0) then
           write(htopstr,'(a,i0)') 'H',nhtop(i)
        else
           write(htopstr,'(a)') '    '
        end if

        if (idelmt(ncleft(i)) > 0) then
           write(cleftstr,'(a,i0)') 'C',idelmt(ncleft(i))
        else
           write(cleftstr,'(a)') '    '
        end if

        if (idelmt(ncrght(i)) > 0) then
           write(crightstr,'(a,i0)') 'C',idelmt(ncrght(i))
        else
           write(crightstr,'(a)') '    '
        end if

        if (idelmt(nctop(i)) > 0) then
           write(ctopstr,'(a,i0)') 'C',idelmt(nctop(i))
        else
           write(ctopstr,'(a)') '    '
        end if

        if (idelmt(nileft(i)) > 0) then
           write(ileftstr,'(a,i0)') 'I',idelmt(nileft(i))
        else
           write(ileftstr,'(a)') '    '
        end if

        if (idelmt(nirght(i)) > 0) then
           write(irightstr,'(a,i0)') 'I',idelmt(nirght(i))
        else
           write(irightstr,'(a)') '    '
        end if

        if (idelmt(nitop(i)) > 0) then
           write(itopstr,'(a,i0)') 'I',idelmt(nitop(i))
        else
           write(itopstr,'(a)') '    '
        end if

        write (38,1200) i, elmtyp(elmt(i)), idelmt(i),
     1      hleftstr, hrightstr, htopstr,
     1      cleftstr, crightstr, ctopstr,
     1      ileftstr, irightstr, itopstr

c    removed 10-9-2003 jrf
c        write (38,1200) i, elmtyp(elmt(i)), idelmt(i),
c     1      hildat(nhleft(i)), hildat(nhrght(i)), hildat(nhtop(i)),
c    1      chndat(idelmt(ncleft(i))), chndat(idelmt(ncrght(i))),
c     1      chndat(idelmt(nctop(i))), impdat(idelmt(nileft(i))),
c     1      impdat(idelmt(nirght(i))), impdat(idelmt(nitop(i)))
c
   20 continue
c
   30 nelmt = i - 1
c
c     check #3 --> highest hillslope element in watershed structure
c     file must equal requested number of hillslopes
c
      if (nhmax.ne.nhill) then
        write (6,1600) nhmax, nhill
        stop
      end if
c
c     read in information from channel file
c
      call eatcom(18)
      read (18,*) chntmp
c
c     check #4 --> a) cross check all of the # channel inputs
c     w.r.t. structure (nchan) vs. management (jstruct) vs. channel
c     file (chntmp); b) number of channels read in must be less
c     than or equal to mxplan
c
      if ((chntmp.ne.jstruc).or.(chntmp.ne.nchan)) then
        write (6,1700) chntmp, jstruc, nchan
        stop
      else if (nchan.gt.mxplan) then
        write (6,1800) nchan, mxplan
        stop
      end if
c
      read (18,*) ipeak
cw Added by L. Wang, 6/2/2010.
c      ipeakm = ipeak
c      if(ipeak>=40 .and. ipeak<=49) ipeak = 4
cw End adding.
      read (18,*) lw
c
      do 40 ichan = 1, nchan
c
c       write (38,2400) ichan
c
        ncsseg(ichan) = nslpts(ichan)
c
        read (18,*)
        read (18,*)
        read (18,*)
c
        read (18,*) ishape(ichan)
        if (ishape(ichan).ge.2) ishape(ichan)=3
        read (18,*) icntrl(ichan)
        read (18,*) ienslp(ichan)
        read (18,*) flgout(ichan)
c
        flgout(ichan) = watsum
        chnlen(ichan) = slplen(ichan)
c
        read (18,*) chnz(ichan), chnnbr(ichan)
c
        chnwid(ichan) = fwidth(ichan)
c
        read (18,*) chnn(ichan), chnk(ichan), chntcr(ichan),
     1      chnedm(ichan), chneds(ichan)
c
c       if channel is naturally eroded then set the hydraulic
c       roughness equal to the bare soil roughness
c
        if ((ishape(ichan).eq.3).and.(chnn(ichan).gt.chnnbr(ichan)))
     1      then
c          chnn(ichan) = chnnbr(ichan)
c          write (38,1900)
        end if
c
        if (chnn(ichan).lt.chnnbr(ichan)) then
          chnn(ichan) = chnnbr(ichan)
          write (38,2000)
        end if
c
        chnks(ichan) = ks(ichan)
c
c       read in control section parameters
c
        read (18,*) ctlslp(ichan), ctlz(ichan), ctln(ichan)
c
c       modify ctln(ichan), ctlz(ichan) if no control section
c
        if (icntrl(ichan).eq.0) then
          ctln(ichan) = chnn(ichan)
          ctlz(ichan) = chnz(ichan)
          ctlslp(ichan) = slplst
c
        end if
c
        if (icntrl(ichan).eq.4) then
          read (18,*) rccoef(ichan), rcexp(ichan), rcoset(ichan)
          write (38,2100)
          write (38,2200) rccoef(ichan), rcexp(ichan), rcoset(ichan)
        end if
c
CAS CAS Added by A. Srivastava 3/21/2016
CAS Channel critical shear stress is determined based on the relationship 
CAS between channel slope and channel shear stress for steep mountainous
CAS forests. Citation: Bunte, K., S. R. Abt, K. W. Swingle, D. A. Cenderelli, 
CAS and J. M. Schneider (2013), Critical Shields values in coarse-bedded steep streams, 
CAS Water Resour. Res., 49, 7427�7447, doi:10.1002/2012WR012672.
        if (tcrflg .eq. 1) then
            chntcr(ichan) = 99.0 + 14.2 * alog(chnslp(ichan,1))
CAS For the above relationship that gives negative values.            
            if (chntcr(ichan) .lt. 0.001) chntcr(ichan) = 0.001
            if (chntcr(ichan) .gt. 99.0) chntcr(ichan) = 99.0
        endif
        !!write(*,*)ichan,chnslp(ichan,1),chntcr(ichan)
CAS End Adding.
c
        ctlslp(ichan) = sin(atan(ctlslp(ichan)))
c
   40 continue
c Added by L. Wang, 08/20/2009.
      if(ipeak > 2) then
          cbase = 0.
          mofapp = 1
          open(24, file='chan.inp', status='old', err=100)
          read(24, *, err=100, end=100) ichout, dtchr
          read(24, *) cbase
          read(24, *, err=101, end=101) nchnum
          read(24, *, err=102, end=102) (ichnum(ichan), ichan=1,nchnum)
          close(24)
          if(ichout < 0) ichout = 0
          if(nchnum < 0) nchnum = 0
c          if(nchnum > 10) nchnum = 10
          if(nchnum > nchan) nchnum = nchan
          goto 110
100       ichout = 0
101       nchnum = 0
102       continue
110       continue
      endif
          if(dtchr < dtlowl) dtchr = dtlowl
          if(imodel == 1) then
             if(dtchr > dtupl1) dtchr = dtupl1
          else
             if(dtchr > dtupl2) dtchr = dtupl2
          endif
          ntchr = 86400./dtchr + 0.99
          if(ntchr > mxtchr) ntchr = mxtchr
          dtchr = 86400./ntchr
          do ichan=1,nchan
              q1(ntchr,ichan) = -1.e6   ! A large negative number to indicate that it has not been updated yet.
              qinich(ichan) = -1.e6
              qlich(ichan) = -1.e6
          enddo
      if(ichout > 0 .and. nchnum >0) then
          open(66, file='chan.out', status='unknown')
          open(67, file='chanwb.out', status='unknown')
          write(66, *) 'Channel Routing Output'
          write(67, *) 'Channel Water Balance'
          write(67, 2700)
          if(ipeak == 3) write(66, *)'  Kinematic wave method'
          if(ipeak == 4) write(66, *)'  Muskingum-Cunge method'
          if(ipeak == 5) write(66, *)
     1                     '  Muskingum-Cunge method (mod 3 point)'
          if(ichout == 1) write(66, 2400)
          if(ichout == 2) write(66, 2500)
          if(ichout >= 3) write(66, 2600)
      endif
c End adding.
c
      return
c1000 format ('ichan ',i1,' nslpts ',i2,' pchnslp ',f5.4,' pctlslp ',f5
c    1    .4)
c1100 format ('ichan ',i1,' nslpts ',i2,' chnslp  ',f5.4,'  ctlslp ',f5
c    1    .4)
c
 1200 format (i4,3x,a7,i4,1x,9(2x,a4))
 1300 format (//18x,'WATERSHED STRUCTURE INPUT FILE',/,18x,30('-'),//,
     1    'Hillslope Elements: 1-',i4,//,28x,'(CONTRIBUTING ',
     1    'ELEMENTS MATRIX)',/,23x,'HILLSLOPE',10x,'CHANNEL',8x,
     1    'IMPOUNDMENT',/,'ELEM.',4x,'ELEMENT',/,1x,'#',5x,'FED',4x,
     1    'NUM',4x,3('L',5x,'R',5x,'T',5x),/,3('-'),4x,3('-'),4x,3('-'),
     1    3x,3(3('-'),3x,3('-'),3x,3('-'),3x)/)
 1400 format (//' Hillslopes requested in main input : ',i2,/,
     1    ' Hillslopes read in pass file       : ',i2,//,
     1    ' Program stop - # input hillslopes must be less than',/,
     1    ' or equal to # pass file hillslopes')
 1500 format (//' Program stop - element read in having no',
     1    ' hydrologic link',/,' with the rest of the watershed')
 1600 format (//' Hillslopes read in structure file  : ',i2,/,
     1    ' Hillslopes requested in main input : ',i2,//,
     1    ' Program stop - # input hillslopes must be equal to',/,
     1    ' # structure file hillslopes')
 1700 format (//' Channels read in channel file    : ',i2,/,
     1    ' Channels read in management file : ',i2,//,
     1    ' Channels read in structure file  : ',i2,//,
     1    ' Program stop - # channels must be the same in all',
     1    ' three files')
 1800 format (//' Number of channels in watershed : ',i3,/,
     1    ' Maximum allowable channels      : ',i3,//,
     1    ' Program stop - reduce number of channels')
c1900 format (/1x,'**** ISHAPE=3, SO CHNN SET EQUAL TO CHNNBR **** ')
 2000 format (/1x,'**** CHNN CANNOT BE LESS THAN CHNNBR - CHNN SET',
     1    ' EQUAL TO CHNNBR **** ')
 2100 format (9x,'  RCOEF  RCEXP RCOSET')
 2200 format ('Line 10: ',3f7.2/)

 2400 format(/,'Peak Flow Time and Rate',//,
     1         '  Year    Day   Elmt_ID Chan_ID  Time(s) ', 
     1       'Peak_Discharge(m^3/s)')
 2500 format(/,'Daily Average Flow Rate',//,
     1         '  Qavg   = Daily average discharge, m^3/s',/,
     1         '  Runvol = Total runoff, m^3',//,
     1           '  Year    Day   Elmt_ID Chan_ID    Qavg       Runvol')
 2600 format(/,'Timestep Flow Rate',//,
     1          '  Year    Day   Elmt_ID Chan_ID  Time(s)  ',
     1          'Discharge(m^3/s)')
 2700 format(/,'  Inflow  = Total inflow above channel outlet, ',
     1         'includes baseflow, all sources m^3', /,
     1         '  Outflow = Water flow out of channel outlet, m^3', /,
     1         '  Storage = Water surface storage at the end of the ',
     1         'day, m^3',/,
     1         '  Baseflow = Portion of inflow from baseflow, m^3',/,
     1         '  Loss = Transmission loss in channel, ',
     1         'infiltration, m^3',/,
     1         '  Balance = Water balance error at end of day, ',
     1         '0=balanced m^3',/,
     1         '     inflow-outflow-loss-(change in surface storage)'
c Modified, L. Wang, 11/21/2011
c      1       /,'  Time    = Water residence time based on daily outflow'
c     1         ' and initial storage, day',
     1      //,'  Year    Day  Elmt_ID Chan_ID    Inflow  ',
     1         '  Outflow   Storage    Baseflow       Loss    Balance')
CAS Added by A. Srivastava 3/21/2016
 2800 format (//'->Channel critical shear stress is based on channel 
     1            slope steepness'//)
CAS End adding.
      end
