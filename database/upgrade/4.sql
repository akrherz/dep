--- Add scenario support
create table scenarios (id int UNIQUE, label varchar);

insert into scenarios(id, label) values (0, 'Production');
insert into scenarios(id, label) values (1, 'G4');
insert into scenarios(id, label) values (2, 'dbfsOrgnlTesting');
GRANT SELECT on scenarios to nobody,apache;

alter table flowpath_points add scenario int references scenarios(id);
alter table flowpaths add scenario int references scenarios(id);
alter table results add scenario int references scenarios(id);
alter table results_by_huc12 add scenario int references scenarios(id);

update flowpath_points set scenario = 0;
update flowpaths set scenario = 0;
update results set scenario = 0;
update results_by_huc12 set scenario = 0;