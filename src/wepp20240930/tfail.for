      subroutine tfail(efflen,nowcrp)
c********************************************************************
c                                                                   *
c     This subroutine called from SR CONTIN determines if the       *
c     contours for a flow element and storm fail or not.            *
c     If failure occurs then cnfail(iplane)=1, if contour holds     *
c     then cnfail(iplane) = 0.                                      *
c                                                                   *
c********************************************************************
c********************************************************************
c                                                                   *
c   Arguments                                                       *
c     nowcrp - current crop                                         *
c                                                                   *
c********************************************************************
c                                                                   *
c
      include 'pmxcrp.inc'
      include 'pmxelm.inc'
      include 'pmxhil.inc'
      include 'pmxpln.inc'
      include 'pmxslp.inc'
CAS Added by A. Srivastava 3/21/2016
      include 'pmxnsl.inc'
      include 'pntype.inc'
      include 'pmxtls.inc'
      include 'pmxtil.inc'
CAS End adding.
c
      integer nowcrp
c
c********************************************************************
c                                                                   *
c   Common Blocks                                                   *
c                                                                   *
c********************************************************************
c
      include 'ccntour.inc'
      include 'cconsta.inc'
c
      include 'cdist.inc'
c
      include 'cends.inc'
c
      include 'cffact.inc'
c
      include 'chydrol.inc'
c
      include 'cslope.inc'
c
      include 'cstruc.inc'
CAS Added by A. Srivastava 3/21/2016
      include 'cnew.inc'
c     read manver      
      include 'ccrpout.inc'
c     read rh
      include 'cupdate.inc'
c     read sdate, year
      include 'cslinit.inc'
c     read riinit
CAS End adding.
c
c********************************************************************
c                                                                   *
c  Local Variables                                                  *
c    s      :                                                       *
c    h      :                                                       *
c    w      :                                                       *
c    qr     :                                                       *
c    term1  :                                                       *
c    term2  :                                                       *
c    term3  :                                                       *
c    term4  :                                                       *
c    slpang :                                                       *
c    rowang :                                                       *
c    delcon :                                                       *
c    chezch : Chezy discharge coef.                                 *
c    sinrms :                                                       *
c    dtest  :                                                       *
c    dfail  :                                                       *
c                                                                   *
c********************************************************************
c
      real chezch, qr, h, w, s, slpang, rowang, dfail, dtest, sinrms
      real term1, term2, term3a, term3b, term3, term4, efflen, delcon
c
c      Assume a triangular cross section, with dimensions defined by
c      user inputs - rowspc and rdghgt.
c
c      Determine the values of the controlling geometric angles.
c
      s = avgslp(iplane)
c
CAS Added by A. Srivastava 3/21/2016
      if ((manver .ge. 2016.3).and.(contours_perm .eq. 0)) then
CAS   NRCS version: They suggested to replace countour ridge height 
CAS   and contour row spacing with tillage ridge height and rill space,
CAS   respectively.
          if (tildate(iplane) .eq. 0) then
              h = rh(iplane)
              w = rspace(iplane)
          else
              h = rh(iplane)
              w = riinit(iplane)
          endif
      else
          h = rdghgt(conseq(nowcrp,iplane))
          w = rowspc(conseq(nowcrp,iplane))
      endif
CAS End adding.
      slpang = atan(s)
      rowang = atan(h/(0.5*w))
c
CAS Added by A. Srivastava to test 'h', 'w', 'slpang', 'rowang'. 3/21/2016
     !! write(*,2000)sdate,year,h,w,cntslp(conseq(nowcrp,iplane)),
     !!1 avgslp(iplane),slpang,rowang
CAS
c
c     Test to see if the contour slope is the same as the average
c     slope of the OFE - if it is predict that contours fail
c     since water is moving in same direction as profile description
c
      if (cntslp(conseq(nowcrp,iplane)).ge.avgslp(iplane)) then
c       cnfail(iplane)=1
CAS Uncommented previous line (now using cnfail(iplane) variable to 
CAS switch off contours from next day onwards until enabled again).
        cnfail(iplane)=1
        failflg(iplane) = failflg(iplane) + 1
CAS End adding/modifying
        write (6,1000)
        fail(1,iplane) = fail(1,iplane) + 1
        return
      end if
c
c     Test to see if slope angle exceeds the row angle. If it does
c     the contours will fail.
c
      if (slpang.ge.rowang) then
c       cnfail(iplane) = 1
CAS Uncommented previous line
        cnfail(iplane)=1
        failflg(iplane) = failflg(iplane) + 1
CAS End adding/modifying
        write (6,1100)
        fail(2,iplane) = fail(2,iplane) + 1
        return
      end if
c
c
c     If the row angle is greater than the slope angle, determine if
c     the portion of the wetted perimeter on the downslope ridge
c     exceeds the actual ridge length
c
c     qr is the volume of runoff (m3/s) at the end of the first
c     contour row, including rainfall excess plus flow from
c     the upper flow element.
c
      qin = qout
      delcon = ((efflen*peakro(iplane))-qin) / slplen(iplane)
      if (delcon.le.0.0) then
        qr = qin * rowspc(conseq(nowcrp,iplane))
      else
        qr = (qin+(delcon*rowlen(conseq(nowcrp,iplane)))) *
     1      rowspc(conseq(nowcrp,iplane))
      end if
c
      chezch = sqrt(8.0*accgav/frctrl(iplane))
c
      term1 = (chezch/(2.0*qr)) *
     1    sqrt(0.5*cntslp(conseq(nowcrp,iplane)))
      sinrms = sin(rowang-slpang)
      term2 = sinrms * sinrms * sinrms
cc
c     original code  10/1/91
c     term3 = ((1.0/tan(rowang+slpang))+(1.0/tan(rowang-slpang)))**1.5
c
c     code changed because of problem with Lahey compiler and tangent
c     function on AT&T 6300 machine  dcf
c
      term3a = (sin(rowang+slpang)) / (cos(rowang+slpang))
      term3b = (sin(rowang-slpang)) / (cos(rowang-slpang))
      term3 = (1.0/term3a+1.0/term3b) ** 1.5
c
c
      term4 = sqrt(1.0+sin(rowang-slpang)/sin(rowang+slpang))
c
c     Compute the length of the downslope portion of wetted perimeter
c
      dtest = (term1*term2*term3/term4) ** (-0.4)
c
c     Compute the actual length of the ridge side.
c
      dfail = sqrt(h*h+0.25*w*w)
c
c     Test for failure
c
      if (dtest.ge.dfail) then
c
c       CONTOURS FAIL
c
c       cnfail(iplane)=1
CAS Uncommented previous line
        cnfail(iplane)=1
        failflg(iplane) = failflg(iplane) + 1
CAS End adding/modifying
        write (6,1200)
        fail(3,iplane) = fail(3,iplane) + 1
c
      else
c
c       CONTOURS HOLD
c
c       cnfail(iplane)=0
CAS Uncommented previous line
        cnfail(iplane)=0
        write (6,1300)iplane,sdate
CAS End adding/modifying
      end if
c
      return
 1000 format (1x,/,10x,'Contours Failed - contour slope is > = the ',
     1    'average slope')
 1100 format (1x,/,10x,'Contours Failed slope angle exceeds the row ',
     1    'sideslope angle')
 1200 format (1x,/,10x,'Contours Failed')
CAS
 1300 format (1x,/,10x,'Contours Held on Plane ',i2,' on Day ',i4)
CAS
!!CAS
 !!2000  format(1x,2(1x,I4),6(1x,F7.5))
 !!3000  format(1x,3(1x,I4),6(1x,F7.5))
!!CAS
      end
