
c     begin include file cpart1.inc

c     + + + COMMON BLOCK DESCRIPTION + + +
c     + + + INSERT DESCRIPTION HERE  + + +

c     NOTE : PART1 is used in SR ROUTE.

      common /part1/    npart,frac(mxpart,mxelem),usr_partsize

c     + + + VARIABLE DECLARATIONS + + +

      integer           npart
      real              frac
      integer           usr_partsize

c     + + + VARIABLE DEFINITIONS + + +

c     npart               : number of particle classes
c     frac(mxpart,mxelem) : fraction of each particle class (0-1)
c     usr_partsize        : flag to indicate if user supplied particle classes read

c     end include file cpart1.inc

